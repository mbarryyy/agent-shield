'use client';

import { useState, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { api } from '@/lib/api';
import { useAuth } from '@/lib/auth';
import type { RegisterAgentRequest } from '@elydora/shared';

const TOKEN_EXPIRATION_OPTIONS = [
  { labelKey: '24hours', seconds: 86400 },
  { labelKey: '7days', seconds: 604800 },
  { labelKey: '1month', seconds: 2592000 },
  { labelKey: '1year', seconds: 31536000 },
  { labelKey: 'custom', seconds: -1 },
  { labelKey: 'neverExpire', seconds: null },
] as const;

type ExpirationOption = (typeof TOKEN_EXPIRATION_OPTIONS)[number];

interface AgentRegistrationFormProps {
  onSuccess: () => void;
  onCancel: () => void;
}

function base64urlEncode(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  let binary = '';
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '');
}

function generateAgentId(): string {
  const id = crypto.randomUUID().split('-')[0];
  return `agent-${id}`;
}

interface Credentials {
  agentId: string;
  kid: string;
  publicKey: string;
  privateKey: string;
  orgId: string;
}

// ─── Integration definitions ──────────────────────────────────────────────────

type IntegrationCategory = 'supported' | 'sdk';

interface Integration {
  id: string;
  name: string;
  description: string;
  category: IntegrationCategory;
  agentFlag?: string;
}

const INTEGRATIONS: Integration[] = [
  // Supported (one-command install)
  { id: 'claudecode', name: 'Claude Code', description: 'Anthropic CLI agent', category: 'supported', agentFlag: 'claudecode' },
  { id: 'cursor', name: 'Cursor', description: 'AI-powered code editor', category: 'supported', agentFlag: 'cursor' },
  { id: 'gemini', name: 'Gemini CLI', description: 'Google AI CLI agent', category: 'supported', agentFlag: 'gemini' },
  { id: 'kirocli', name: 'Kiro CLI', description: 'AWS AI CLI agent', category: 'supported', agentFlag: 'kirocli' },
  { id: 'kiroide', name: 'Kiro IDE', description: 'AWS spec-driven AI IDE', category: 'supported', agentFlag: 'kiroide' },
  { id: 'opencode', name: 'OpenCode', description: 'Open-source TUI agent', category: 'supported', agentFlag: 'opencode' },
  { id: 'copilot', name: 'Copilot CLI', description: 'GitHub Copilot CLI agent', category: 'supported', agentFlag: 'copilot' },
  { id: 'letta', name: 'Letta Code', description: 'Letta AI CLI agent', category: 'supported', agentFlag: 'letta' },
  // SDK Integration (code tutorial)
  { id: 'codex', name: 'OpenAI Codex', description: 'OpenAI CLI agent', category: 'sdk' },
  { id: 'kimi', name: 'Kimi', description: 'Moonshot AI assistant', category: 'sdk' },
  { id: 'enterprise', name: 'Custom Enterprise Agent', description: 'Your own internal agent', category: 'sdk' },
  { id: 'gui', name: 'GUI Agent', description: 'Desktop or web-based agent', category: 'sdk' },
  { id: 'other', name: 'Other', description: 'Any custom integration', category: 'sdk' },
];

// ─── Component ────────────────────────────────────────────────────────────────

export default function AgentRegistrationForm({ onSuccess, onCancel }: AgentRegistrationFormProps) {
  const { t } = useTranslation();
  const { user } = useAuth();
  const [displayName, setDisplayName] = useState('');
  const [responsibleEntity, setResponsibleEntity] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Success state
  const [credentials, setCredentials] = useState<Credentials | null>(null);
  const [copiedField, setCopiedField] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<'node' | 'python' | 'go'>('node');

  // Multi-step success flow
  const [successStep, setSuccessStep] = useState<'credentials' | 'integration'>('credentials');
  const [selectedIntegration, setSelectedIntegration] = useState<Integration | null>(null);

  // Token expiration
  const [tokenExpiration, setTokenExpiration] = useState<ExpirationOption>(TOKEN_EXPIRATION_OPTIONS[0]);
  const [customDays, setCustomDays] = useState('');
  const [apiToken, setApiToken] = useState<string | null>(null);
  const [issuingToken, setIssuingToken] = useState(false);
  const [tokenError, setTokenError] = useState<string | null>(null);

  const copyToClipboard = useCallback(async (text: string, field: string) => {
    await navigator.clipboard.writeText(text);
    setCopiedField(field);
    setTimeout(() => setCopiedField(null), 2000);
  }, []);

  const handleSubmit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      setError(null);

      if (!displayName.trim()) {
        setError(t('agentRegistration.displayNameRequired'));
        return;
      }

      setSubmitting(true);
      try {
        // Generate Agent ID and keypair
        const agentId = generateAgentId();
        const keyPair = await crypto.subtle.generateKey('Ed25519', true, ['sign', 'verify']);
        const pkcs8 = await crypto.subtle.exportKey('pkcs8', keyPair.privateKey);
        const rawPublic = await crypto.subtle.exportKey('raw', keyPair.publicKey);

        const seed = new Uint8Array(pkcs8).slice(-32);
        const kid = `${agentId}-key-1`;
        const publicKey = base64urlEncode(rawPublic);
        const privateKey = base64urlEncode(seed.buffer);

        // Register with backend
        const body: RegisterAgentRequest = {
          agent_id: agentId,
          display_name: displayName.trim(),
          responsible_entity: responsibleEntity.trim() || undefined,
          keys: [{ kid, public_key: publicKey, algorithm: 'ed25519' }],
        };
        await api.agents.register(body);

        // Show success screen with credentials
        setCredentials({
          agentId,
          kid,
          publicKey,
          privateKey,
          orgId: user?.org_id ?? '',
        });
        setSuccessStep('credentials');
      } catch (err) {
        setError(err instanceof Error ? err.message : t('agentRegistration.failedToRegister'));
      } finally {
        setSubmitting(false);
      }
    },
    [displayName, responsibleEntity, user, t],
  );

  const handleIssueToken = useCallback(async () => {
    setTokenError(null);
    setIssuingToken(true);
    try {
      let ttlSeconds: number | null;
      if (tokenExpiration.seconds === null) {
        ttlSeconds = null;
      } else if (tokenExpiration.seconds === -1) {
        const days = parseInt(customDays, 10);
        if (!days || days < 1) {
          setTokenError(t('agentRegistration.enterValidDays'));
          return;
        }
        ttlSeconds = days * 86400;
      } else {
        ttlSeconds = tokenExpiration.seconds;
      }
      const result = await api.auth.issueToken(ttlSeconds);
      setApiToken(result.token);
    } catch (err) {
      setTokenError(err instanceof Error ? err.message : t('agentRegistration.failedToIssueToken'));
    } finally {
      setIssuingToken(false);
    }
  }, [tokenExpiration, customDays, t]);

  // ─── Success Screen ───────────────────────────────────────────────────
  if (credentials) {
    const creds = credentials; // narrowed non-null for closures
    const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL ?? 'http://localhost:8787';
    // CLI install commands for supported integrations
    const buildCliCommands = (integration: Integration) => ({
      node: `npx @elydora/sdk install --agent ${integration.agentFlag} --org_id "${creds.orgId}" --agent_id "${creds.agentId}" --private_key "${creds.privateKey}" --kid "${creds.kid}" --token "${apiToken ?? ''}" --base_url "${apiBaseUrl}"`,
      python: `pip install elydora && elydora install --agent ${integration.agentFlag} --org_id "${creds.orgId}" --agent_id "${creds.agentId}" --private_key "${creds.privateKey}" --kid "${creds.kid}" --token "${apiToken ?? ''}" --base_url "${apiBaseUrl}"`,
      go: `go install github.com/Elydora-Infrastructure/Elydora-Go-SDK/cmd/elydora@latest && elydora install --agent ${integration.agentFlag} --org_id "${creds.orgId}" --agent_id "${creds.agentId}" --private_key "${creds.privateKey}" --kid "${creds.kid}" --token "${apiToken ?? ''}" --base-url "${apiBaseUrl}"`,
    });

    // SDK step-by-step tutorial (used for unsupported / SDK integrations)
    type TutorialStep = { title: string; description: string; code: string };

    // Daemon script content (shared across all languages — always Node.js)
    const daemonCode = `#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { recordOperation } from './client.mjs';

// Self-locate: daemon lives in ~/.elydora/{agentId}/
const AGENT_DIR = path.dirname(fileURLToPath(import.meta.url));
const QUEUE_DIR = path.join(AGENT_DIR, 'queue');
const PROCESSED_DIR = path.join(AGENT_DIR, 'processed');
const PID_FILE = path.join(AGENT_DIR, 'daemon.pid');
const LOG_FILE = path.join(AGENT_DIR, 'daemon.log');

fs.mkdirSync(QUEUE_DIR, { recursive: true });
fs.mkdirSync(PROCESSED_DIR, { recursive: true });
fs.writeFileSync(PID_FILE, String(process.pid));

function log(msg) {
  fs.appendFileSync(LOG_FILE, \`[\${new Date().toISOString()}] \${msg}\\n\`);
}

log(\`Daemon started (pid \${process.pid})\`);

async function processFile(filePath) {
  try {
    const data = JSON.parse(fs.readFileSync(filePath, 'utf-8'));
    const { tool_name, tool_input, session_id } = data;
    if (!tool_name) { log(\`SKIP \${filePath}: missing tool_name\`); return; }
    await recordOperation({
      operationType: 'ai.tool_use',
      subject: { session_id: session_id || 'unknown' },
      action: { tool: tool_name },
      payload: { tool_name, tool_input: tool_input || {}, session_id: session_id || 'unknown' },
    });
    fs.renameSync(filePath, path.join(PROCESSED_DIR, path.basename(filePath)));
    log(\`OK \${path.basename(filePath)}\`);
  } catch (err) {
    log(\`ERR \${path.basename(filePath)}: \${err.message}\`);
  }
}

async function poll() {
  try {
    const files = fs.readdirSync(QUEUE_DIR).filter(f => f.endsWith('.json')).sort();
    for (const f of files) await processFile(path.join(QUEUE_DIR, f));
  } catch {}
  setTimeout(poll, 500);
}
poll();

process.on('exit', () => { try { fs.unlinkSync(PID_FILE); } catch {} });
process.on('SIGINT', () => process.exit());
process.on('SIGTERM', () => process.exit());`;

    // Agent-specific persistent instructions content
    function buildAgentInstructions(integrationId: string): TutorialStep {
      const agentDir = `~/.elydora/${creds.agentId}`;
      const agentDirWin = `$env:USERPROFILE\\.elydora\\${creds.agentId}`;

      const queueInstr = `After EVERY tool call, write a JSON file to the queue directory.
The daemon will pick it up automatically and submit to Elydora.

IMPORTANT: Only access your own directory ${agentDir}/ — do NOT read or modify other agent directories.

# macOS / Linux
echo '{"tool_name":"TOOL_NAME","tool_input":{},"session_id":"SESSION_ID"}' > ${agentDir}/queue/$(date +%s)_$$_$RANDOM.json

# Windows (PowerShell)
'{"tool_name":"TOOL_NAME","tool_input":{},"session_id":"SESSION_ID"}' | Out-File "${agentDirWin}\\queue\\$([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()).json"

Every single tool use must be logged. No exceptions.`;

      if (integrationId === 'codex') {
        return {
          title: 'Start daemon + create Codex skill',
          description: 'Start the queue daemon and create a Codex skill so every future session automatically logs tool use.',
          code: `# Start the daemon:
# macOS / Linux:   nohup node ${agentDir}/daemon.mjs >> ${agentDir}/daemon.log 2>&1 &
# Windows:         Start-Process -NoNewWindow node -ArgumentList "${agentDirWin}\\daemon.mjs"

# Create the skill directory:
# macOS / Linux:  mkdir -p ~/.codex/skills/elydora-audit
# Windows:        New-Item -ItemType Directory -Force "$env:USERPROFILE\\.codex\\skills\\elydora-audit" | Out-Null

# Write ~/.codex/skills/elydora-audit/SKILL.md:
---
name: elydora-audit
description: Log every tool use to Elydora. MUST be active at all times.
---

# Elydora Audit Logging (MANDATORY)

${queueInstr}`,
        };
      }

      if (integrationId === 'kimi') {
        return {
          title: 'Start daemon + add Kimi instructions',
          description: 'Start the queue daemon and add logging instructions to KIMI.md so every future session logs tool use.',
          code: `# Start the daemon:
# macOS / Linux:   nohup node ${agentDir}/daemon.mjs >> ${agentDir}/daemon.log 2>&1 &
# Windows:         Start-Process -NoNewWindow node -ArgumentList "${agentDirWin}\\daemon.mjs"

# Append to KIMI.md in your project root (create if needed):

## Elydora Audit Logging (MANDATORY)

${queueInstr}`,
        };
      }

      return {
        title: 'Start daemon + add agent instructions',
        description: 'Start the queue daemon and add logging instructions to your agent\'s persistent instructions file.',
        code: `# Start the daemon:
# macOS / Linux:   nohup node ${agentDir}/daemon.mjs >> ${agentDir}/daemon.log 2>&1 &
# Windows:         Start-Process -NoNewWindow node -ArgumentList "${agentDirWin}\\daemon.mjs"

# Add the following to your agent's instructions file (system prompt, instructions.md, AGENTS.md, etc.):

## Elydora Audit Logging (MANDATORY)

${queueInstr}`,
      };
    }

    // Build tutorial steps: setup → client → daemon → start+instructions → log → verify
    function buildSdkTutorialSteps(lang: 'node' | 'python' | 'go', integrationId: string): TutorialStep[] {
      const agentDir = `~/.elydora/${creds.agentId}`;
      const agentDirWin = `$env:USERPROFILE\\.elydora\\${creds.agentId}`;

      // Step 1: setup directory + install SDK (shared at ~/.elydora/, agent subdir created)
      const setupStep: TutorialStep = lang === 'node' ? {
        title: 'Create ~/.elydora/ and install SDK',
        description: `Install the SDK at ~/.elydora/ (shared) and create your agent directory at ${agentDir}/.`,
        code: `# macOS / Linux
mkdir -p ~/.elydora && cd ~/.elydora && npm init -y && npm install @elydora/sdk
mkdir -p ${agentDir}

# Windows (PowerShell)
New-Item -ItemType Directory -Force "$env:USERPROFILE\\.elydora" | Out-Null
cd "$env:USERPROFILE\\.elydora"; npm init -y; npm install @elydora/sdk
New-Item -ItemType Directory -Force "${agentDirWin}" | Out-Null`,
      } : lang === 'python' ? {
        title: 'Create ~/.elydora/ and install SDK',
        description: `Install the SDK at ~/.elydora/ (shared) and create your agent directory at ${agentDir}/.`,
        code: `# macOS / Linux
mkdir -p ~/.elydora && cd ~/.elydora
npm init -y && npm install @elydora/sdk   # daemon always uses Node.js
python -m venv .venv && source .venv/bin/activate && pip install elydora
mkdir -p ${agentDir}

# Windows (PowerShell)
New-Item -ItemType Directory -Force "$env:USERPROFILE\\.elydora" | Out-Null
cd "$env:USERPROFILE\\.elydora"
npm init -y; npm install @elydora/sdk
python -m venv .venv; .venv\\Scripts\\Activate.ps1; pip install elydora
New-Item -ItemType Directory -Force "${agentDirWin}" | Out-Null`,
      } : {
        title: 'Create ~/.elydora/ and install SDK',
        description: `Install the SDK at ~/.elydora/ (shared) and create your agent directory at ${agentDir}/.`,
        code: `# macOS / Linux
mkdir -p ~/.elydora && cd ~/.elydora
npm init -y && npm install @elydora/sdk   # daemon always uses Node.js
go mod init elydora-audit && go get github.com/Elydora-Infrastructure/Elydora-Go-SDK
mkdir -p ${agentDir}

# Windows (PowerShell)
New-Item -ItemType Directory -Force "$env:USERPROFILE\\.elydora" | Out-Null
cd "$env:USERPROFILE\\.elydora"
npm init -y; npm install @elydora/sdk
go mod init elydora-audit; go get github.com/Elydora-Infrastructure/Elydora-Go-SDK
New-Item -ItemType Directory -Force "${agentDirWin}" | Out-Null`,
      };

      // Step 2: create client.mjs in agent subdirectory
      const clientStep: TutorialStep = {
        title: 'Create client.mjs',
        description: `Create ${agentDir}/client.mjs — the pre-configured ElydoraClient used by the daemon.`,
        code: `import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { ElydoraClient } from '@elydora/sdk';

const AGENT_ID = '${creds.agentId}';
const AGENT_DIR = path.join(os.homedir(), '.elydora', AGENT_ID);
const CHAIN_STATE_PATH = path.join(AGENT_DIR, 'chain-state.json');
const ZERO_CHAIN_HASH = 'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA';

function readChainState() {
  try { return JSON.parse(fs.readFileSync(CHAIN_STATE_PATH, 'utf-8')).prev_chain_hash || ZERO_CHAIN_HASH; }
  catch { return ZERO_CHAIN_HASH; }
}
function writeChainState(h) {
  fs.mkdirSync(AGENT_DIR, { recursive: true });
  fs.writeFileSync(CHAIN_STATE_PATH, JSON.stringify({ prev_chain_hash: h }));
}

export const client = new ElydoraClient({
  orgId: '${creds.orgId}',
  agentId: AGENT_ID,
  privateKey: '${creds.privateKey}',
  kid: '${creds.kid}',
  baseUrl: '${apiBaseUrl}',
});
client.setToken('${apiToken ?? ''}');
client.prevChainHash = readChainState();

export async function recordOperation({ operationType, subject, action, payload, verify = false }) {
  const eor = client.createOperation({ operationType, subject, action, payload });
  const { receipt } = await client.submitOperation(eor);
  if (receipt?.chain_hash) { client.prevChainHash = receipt.chain_hash; writeChainState(receipt.chain_hash); }
  if (!verify) return { eor, receipt };
  const verification = await client.verifyOperation(receipt.operation_id);
  return { eor, receipt, verification };
}`,
      };

      // Step 3: create daemon.mjs in agent subdirectory
      const daemonStep: TutorialStep = {
        title: 'Create daemon.mjs',
        description: `Create ${agentDir}/daemon.mjs — the queue watcher that automatically submits operations to Elydora.`,
        code: daemonCode,
      };

      // Step 4: start daemon + agent instructions
      const instructionsStep = buildAgentInstructions(integrationId);

      // Step 5: log tool use — primary (queue) + alternative (direct)
      const logStep: TutorialStep = lang === 'node' ? {
        title: 'Log tool use',
        description: 'After every tool call, write a JSON file to the queue. The daemon handles the rest. Alternative: call recordOperation() directly for faster submission.',
        code: `// PRIMARY — write to queue (daemon submits automatically)
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const queueDir = path.join(os.homedir(), '.elydora', '${creds.agentId}', 'queue');
fs.mkdirSync(queueDir, { recursive: true });
fs.writeFileSync(
  path.join(queueDir, \`\${Date.now()}-\${Math.random().toString(36).slice(2)}.json\`),
  JSON.stringify({ tool_name: toolName, tool_input: toolInput, session_id: sessionId }),
);

// ALTERNATIVE — direct SDK call (faster, bypasses daemon)
import { homedir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
const { recordOperation } = await import(
  pathToFileURL(join(homedir(), '.elydora', '${creds.agentId}', 'client.mjs')).href
);
await recordOperation({
  operationType: 'ai.tool_use',
  subject: { session_id: sessionId },
  action: { tool: toolName },
  payload: { tool_name: toolName, tool_input: toolInput, session_id: sessionId },
});`,
      } : lang === 'python' ? {
        title: 'Log tool use',
        description: 'After every tool call, write a JSON file to the queue. The daemon handles the rest. Alternative: call record_operation() directly.',
        code: `# PRIMARY — write to queue (daemon submits automatically)
import json, time
from pathlib import Path

queue_dir = Path.home() / ".elydora" / "${creds.agentId}" / "queue"
queue_dir.mkdir(parents=True, exist_ok=True)
(queue_dir / f"{time.time_ns()}.json").write_text(json.dumps({
    "tool_name": tool_name,
    "tool_input": tool_input,
    "session_id": session_id,
}))

# ALTERNATIVE — write to queue from a separate script (no daemon import needed)
import json, time, os

queue_dir = os.path.join(os.path.expanduser("~"), ".elydora", "${creds.agentId}", "queue")
os.makedirs(queue_dir, exist_ok=True)
payload = {"tool_name": tool_name, "tool_input": tool_input, "session_id": session_id}
filename = f"{int(time.time() * 1e9)}.json"
with open(os.path.join(queue_dir, filename), "w") as f:
    json.dump(payload, f)`,
      } : {
        title: 'Log tool use',
        description: 'After every tool call, write a JSON file to the queue. The daemon handles the rest. Alternative: write to the queue directory directly.',
        code: `// PRIMARY — write to queue (daemon submits automatically)
import (
    "encoding/json"
    "fmt"
    "os"
    "path/filepath"
    "time"
)

home, _ := os.UserHomeDir()
queueDir := filepath.Join(home, ".elydora", "${creds.agentId}", "queue")
os.MkdirAll(queueDir, 0755)
data, _ := json.Marshal(map[string]any{
    "tool_name": toolName, "tool_input": toolInput, "session_id": sessionId,
})
os.WriteFile(filepath.Join(queueDir, fmt.Sprintf("%d.json", time.Now().UnixNano())), data, 0644)

// ALTERNATIVE — write to queue from Go (same approach, different entry point)
queueDir := filepath.Join(os.Getenv("HOME"), ".elydora", "${creds.agentId}", "queue")
payload := fmt.Sprintf(\`{"tool_name":"%s","tool_input":{},"session_id":"session-1"}\`, toolName)
filename := fmt.Sprintf("%d.json", time.Now().UnixNano())
os.WriteFile(filepath.Join(queueDir, filename), []byte(payload), 0644)`,
      };

      // Step 6: verify
      const verifyStep: TutorialStep = lang === 'node' ? {
        title: 'Verify (optional)',
        description: 'Verify the integrity of a recorded operation.',
        code: `import { homedir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
const { client } = await import(
  pathToFileURL(join(homedir(), '.elydora', '${creds.agentId}', 'client.mjs')).href
);
const result = await client.verifyOperation(operationId);
console.log('Signature:', result.checks.signature);
console.log('Chain:',     result.checks.chain);`,
      } : lang === 'python' ? {
        title: 'Verify (optional)',
        description: 'Verify the integrity of a recorded operation.',
        code: `# Verify via the Elydora console UI, or use urllib to call the API:
import urllib.request, json

url = f"${apiBaseUrl}/v1/operations/{operation_id}/verify"
req = urllib.request.Request(url, headers={"Authorization": "Bearer YOUR_TOKEN"})
result = json.loads(urllib.request.urlopen(req).read())
print("Signature:", result["checks"]["signature"])
print("Chain:",     result["checks"]["chain"])`,
      } : {
        title: 'Verify (optional)',
        description: 'Verify the integrity of a recorded operation.',
        code: `result, _ := client.VerifyOperation(operationId)
fmt.Println("Signature:", result.Checks.Signature)
fmt.Println("Chain:",     result.Checks.Chain)`,
      };

      return [setupStep, clientStep, daemonStep, instructionsStep, logStep, verifyStep];
    }

    // ─── Step 1: Credentials ──────────────────────────────────────────
    if (successStep === 'credentials') {
      return (
        <div className="space-y-5">
          {/* Header */}
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 border border-ink flex items-center justify-center bg-ink">
              <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="#EAEAE5" strokeWidth="2">
                <path d="M3 8l4 4 6-7" />
              </svg>
            </div>
            <div>
              <div className="font-sans text-base font-semibold text-ink">{t('agentRegistration.agentRegistered')}</div>
              <div className="font-mono text-[11px] text-ink-dim">{creds.agentId}</div>
            </div>
          </div>

          {/* Private Key Warning */}
          <div className="border-2 border-ink p-4">
            <div className="flex items-center gap-2 mb-2">
              <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
                <path d="M8 1L1 15h14L8 1zM8 6v4M8 12v1" />
              </svg>
              <span className="font-mono text-[11px] font-bold uppercase tracking-wider">
                {t('agentRegistration.privateKeySaveNow')}
              </span>
            </div>
            <p className="font-mono text-[10px] text-ink-dim mb-3">
              {t('agentRegistration.privateKeyWarning')}
            </p>
            <div className="flex items-center gap-2">
              <code className="flex-1 px-3 py-2 bg-surface border border-border font-mono text-[10px] text-ink break-all select-all">
                {creds.privateKey}
              </code>
              <button
                type="button"
                onClick={() => copyToClipboard(creds.privateKey, 'privateKey')}
                className="shrink-0 px-3 py-2 border border-ink bg-ink text-[#EAEAE5] font-mono text-[10px] uppercase tracking-wider hover:bg-transparent hover:text-ink transition-colors"
              >
                {copiedField === 'privateKey' ? t('common.copied') : t('common.copy')}
              </button>
            </div>
          </div>

          {/* API Token */}
          <div className="border border-border p-4 bg-surface">
            <div className="flex items-center gap-2 mb-2">
              <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
                <path d="M8 1v2M8 13v2M3.05 3.05l1.41 1.41M11.54 11.54l1.41 1.41M1 8h2M13 8h2M3.05 12.95l1.41-1.41M11.54 4.46l1.41-1.41" />
              </svg>
              <span className="font-mono text-[11px] font-bold uppercase tracking-wider">
                {t('agentRegistration.apiToken')}
              </span>
            </div>
            <p className="font-mono text-[10px] text-ink-dim mb-3">
              {t('agentRegistration.apiTokenDesc')}
            </p>

            {apiToken ? (
              <div className="flex items-center gap-2">
                <code className="flex-1 px-3 py-2 bg-white border border-border font-mono text-[10px] text-ink break-all select-all overflow-hidden" style={{ wordBreak: 'break-all' }}>
                  {apiToken}
                </code>
                <button
                  type="button"
                  onClick={() => copyToClipboard(apiToken, 'token')}
                  className="shrink-0 px-3 py-2 border border-ink bg-ink text-[#EAEAE5] font-mono text-[10px] uppercase tracking-wider hover:bg-transparent hover:text-ink transition-colors"
                >
                  {copiedField === 'token' ? t('common.copied') : t('common.copy')}
                </button>
              </div>
            ) : (
              <div className="space-y-3">
                <div>
                  <label className="font-mono text-[10px] text-ink-dim uppercase tracking-wider block mb-1.5">{t('agentRegistration.tokenExpiration')}</label>
                  <div className="flex flex-wrap gap-1.5">
                    {TOKEN_EXPIRATION_OPTIONS.map((opt) => (
                      <button
                        key={opt.labelKey}
                        type="button"
                        onClick={() => setTokenExpiration(opt)}
                        className={`px-2.5 py-1.5 font-mono text-[10px] border transition-colors ${
                          tokenExpiration.labelKey === opt.labelKey
                            ? 'border-ink bg-ink text-[#EAEAE5]'
                            : 'border-border text-ink hover:border-ink'
                        }`}
                      >
                        {t('tokenExpiration.' + opt.labelKey)}
                      </button>
                    ))}
                  </div>
                </div>
                {tokenExpiration.seconds === -1 && (
                  <div className="flex items-center gap-2">
                    <input
                      type="number"
                      min="1"
                      value={customDays}
                      onChange={(e) => setCustomDays(e.target.value)}
                      placeholder={t('agentRegistration.customDays')}
                      className="w-40 px-3 py-1.5 bg-transparent border border-border font-mono text-[11px] text-ink placeholder:text-ink-dim focus:outline-none focus:border-ink transition-colors"
                    />
                    <span className="font-mono text-[10px] text-ink-dim">{t('agentRegistration.days')}</span>
                  </div>
                )}
                {tokenError && (
                  <p className="font-mono text-[10px] text-red-600">{tokenError}</p>
                )}
                <button
                  type="button"
                  onClick={handleIssueToken}
                  disabled={issuingToken}
                  className="px-3 py-2 border border-ink bg-ink text-[#EAEAE5] font-mono text-[10px] uppercase tracking-wider hover:bg-transparent hover:text-ink transition-colors disabled:opacity-50"
                >
                  {issuingToken ? t('agentRegistration.issuing') : t('agentRegistration.issueApiToken')}
                </button>
              </div>
            )}
          </div>

          {/* Credentials Summary */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {[
              { label: t('agentRegistration.credAgentId'), value: creds.agentId, field: 'agentId' },
              { label: t('agentRegistration.credKeyId'), value: creds.kid, field: 'kid' },
              { label: t('agentRegistration.credOrgId'), value: creds.orgId, field: 'orgId' },
              { label: t('agentRegistration.credAlgorithm'), value: 'Ed25519', field: 'algo' },
            ].map((item) => (
              <button
                key={item.field}
                type="button"
                onClick={() => copyToClipboard(item.value, item.field)}
                className="text-left border border-border p-2.5 bg-surface hover:border-ink transition-colors group"
              >
                <div className="font-mono text-[9px] text-ink-dim uppercase tracking-wider mb-0.5">{item.label}</div>
                <div className="font-mono text-[11px] text-ink truncate">{item.value}</div>
                <div className="font-mono text-[9px] text-ink-dim mt-1 opacity-0 group-hover:opacity-100 transition-opacity">
                  {copiedField === item.field ? t('common.copied') : t('common.clickToCopy')}
                </div>
              </button>
            ))}
          </div>

          {/* Continue to integration selector */}
          <div className="flex items-center justify-end pt-2">
            <button
              type="button"
              onClick={() => {
                setSuccessStep('integration');
                setActiveTab('node');
              }}
              className="btn-brutalist"
            >
              {t('common.continue')}
            </button>
          </div>
        </div>
      );
    }

    // ─── Step 2: Integration Selector ─────────────────────────────────
    const supportedIntegrations = INTEGRATIONS.filter((i) => i.category === 'supported');
    const sdkIntegrations = INTEGRATIONS.filter((i) => i.category === 'sdk');

    // If an integration is selected, show the install/code view
    if (selectedIntegration) {
      const isSupported = selectedIntegration.category === 'supported';
      const cliCmds = isSupported ? buildCliCommands(selectedIntegration) : null;
      const steps = !isSupported ? buildSdkTutorialSteps(activeTab, selectedIntegration.id) : null;

      // AI-ready prompt for SDK integrations (copy-paste into any AI agent)
      // Daemon-centric: setup → client → daemon → start + instructions → log via queue
      function buildSdkAiPrompt(lang: 'node' | 'python' | 'go', integrationId: string): string {
        const agentDir = `~/.elydora/${creds.agentId}`;
        const agentDirWin = `$env:USERPROFILE\\.elydora\\${creds.agentId}`;

        const preamble = `Set up Elydora audit logging at ~/.elydora/${creds.agentId}/ (on Windows: $env:USERPROFILE\\.elydora\\${creds.agentId}\\). This is NOT project-specific — do NOT add anything to the current project's dependencies or files. Detect the current OS and use the appropriate commands below.

IMPORTANT: Only access your own directory ${agentDir}/ — do NOT read or modify other agent directories under ~/.elydora/.

IMPORTANT: Every queue JSON file MUST follow this exact structure:
{ "tool_name": "<the tool you used>", "tool_input": <the tool input object>, "session_id": "<your current session ID>" }`;

        // Step 1: install SDK (shared at ~/.elydora/) + create agent subdir
        const setupSteps: Record<'node' | 'python' | 'go', string> = {
          node: `1. Create ~/.elydora/ and install the SDK, then create your agent directory:

# macOS / Linux
mkdir -p ~/.elydora && cd ~/.elydora && npm init -y && npm install @elydora/sdk
mkdir -p ${agentDir}

# Windows (PowerShell)
New-Item -ItemType Directory -Force "$env:USERPROFILE\\.elydora" | Out-Null; cd "$env:USERPROFILE\\.elydora"; npm init -y; npm install @elydora/sdk
New-Item -ItemType Directory -Force "${agentDirWin}" | Out-Null`,

          python: `1. Create ~/.elydora/ and install SDKs (Node.js required for daemon), then create your agent directory:

# macOS / Linux
mkdir -p ~/.elydora && cd ~/.elydora
npm init -y && npm install @elydora/sdk
python -m venv .venv && source .venv/bin/activate && pip install elydora
mkdir -p ${agentDir}

# Windows (PowerShell)
New-Item -ItemType Directory -Force "$env:USERPROFILE\\.elydora" | Out-Null; cd "$env:USERPROFILE\\.elydora"
npm init -y; npm install @elydora/sdk
python -m venv .venv; .venv\\Scripts\\Activate.ps1; pip install elydora
New-Item -ItemType Directory -Force "${agentDirWin}" | Out-Null`,

          go: `1. Create ~/.elydora/ and install SDKs (Node.js required for daemon), then create your agent directory:

# macOS / Linux
mkdir -p ~/.elydora && cd ~/.elydora
npm init -y && npm install @elydora/sdk
go mod init elydora-audit && go get github.com/Elydora-Infrastructure/Elydora-Go-SDK
mkdir -p ${agentDir}

# Windows (PowerShell)
New-Item -ItemType Directory -Force "$env:USERPROFILE\\.elydora" | Out-Null; cd "$env:USERPROFILE\\.elydora"
npm init -y; npm install @elydora/sdk
go mod init elydora-audit; go get github.com/Elydora-Infrastructure/Elydora-Go-SDK
New-Item -ItemType Directory -Force "${agentDirWin}" | Out-Null`,
        };

        // Step 2: client.mjs in agent subdirectory
        const clientStep = `2. Create ${agentDir}/client.mjs with the pre-configured ElydoraClient:

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { ElydoraClient } from '@elydora/sdk';

const AGENT_ID = '${creds.agentId}';
const AGENT_DIR = path.join(os.homedir(), '.elydora', AGENT_ID);
const CHAIN_STATE_PATH = path.join(AGENT_DIR, 'chain-state.json');
const ZERO_CHAIN_HASH = 'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA';

function readChainState() {
  try { return JSON.parse(fs.readFileSync(CHAIN_STATE_PATH, 'utf-8')).prev_chain_hash || ZERO_CHAIN_HASH; }
  catch { return ZERO_CHAIN_HASH; }
}
function writeChainState(h) {
  fs.mkdirSync(AGENT_DIR, { recursive: true });
  fs.writeFileSync(CHAIN_STATE_PATH, JSON.stringify({ prev_chain_hash: h }));
}

export const client = new ElydoraClient({
  orgId: '${creds.orgId}',
  agentId: AGENT_ID,
  privateKey: '${creds.privateKey}',
  kid: '${creds.kid}',
  baseUrl: '${apiBaseUrl}',
});
client.setToken('${apiToken ?? ''}');
client.prevChainHash = readChainState();

export async function recordOperation({ operationType, subject, action, payload, verify = false }) {
  const eor = client.createOperation({ operationType, subject, action, payload });
  const { receipt } = await client.submitOperation(eor);
  if (receipt?.chain_hash) { client.prevChainHash = receipt.chain_hash; writeChainState(receipt.chain_hash); }
  if (!verify) return { eor, receipt };
  const verification = await client.verifyOperation(receipt.operation_id);
  return { eor, receipt, verification };
}`;

        // Step 3: daemon.mjs
        const daemonStep = `3. Create ${agentDir}/daemon.mjs — the queue watcher that automatically submits operations:

${daemonCode}`;

        // Step 4: start daemon + agent-specific persistent instructions
        const queueInstr = `After EVERY tool call, write a JSON file to the queue directory.
The daemon will pick it up automatically and submit to Elydora.

IMPORTANT: Only access your own directory ${agentDir}/ — do NOT read or modify other agent directories.

# macOS / Linux
echo '{"tool_name":"TOOL_NAME","tool_input":{},"session_id":"SESSION_ID"}' > ${agentDir}/queue/$(date +%s)_$$_$RANDOM.json

# Windows (PowerShell)
'{"tool_name":"TOOL_NAME","tool_input":{},"session_id":"SESSION_ID"}' | Out-File "${agentDirWin}\\queue\\$([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()).json"

Every single tool use must be logged. No exceptions.`;

        let instructionsStep: string;
        if (integrationId === 'codex') {
          instructionsStep = `4. Start the daemon and create a Codex skill for persistent auto-logging:

# Start daemon:
# macOS / Linux:   nohup node ${agentDir}/daemon.mjs >> ${agentDir}/daemon.log 2>&1 &
# Windows:         Start-Process -NoNewWindow node -ArgumentList "${agentDirWin}\\daemon.mjs"

# Create skill directory:
# macOS / Linux:   mkdir -p ~/.codex/skills/elydora-audit
# Windows:         New-Item -ItemType Directory -Force "$env:USERPROFILE\\.codex\\skills\\elydora-audit" | Out-Null

# Write ~/.codex/skills/elydora-audit/SKILL.md:
---
name: elydora-audit
description: Log every tool use to Elydora. MUST be active at all times.
---

# Elydora Audit Logging (MANDATORY)

${queueInstr}`;
        } else if (integrationId === 'kimi') {
          instructionsStep = `4. Start the daemon and add Kimi instructions:

# Start daemon:
# macOS / Linux:   nohup node ${agentDir}/daemon.mjs >> ${agentDir}/daemon.log 2>&1 &
# Windows:         Start-Process -NoNewWindow node -ArgumentList "${agentDirWin}\\daemon.mjs"

# Append to KIMI.md in your project root (create if needed):

## Elydora Audit Logging (MANDATORY)

${queueInstr}`;
        } else {
          instructionsStep = `4. Start the daemon and add agent instructions:

# Start daemon:
# macOS / Linux:   nohup node ${agentDir}/daemon.mjs >> ${agentDir}/daemon.log 2>&1 &
# Windows:         Start-Process -NoNewWindow node -ArgumentList "${agentDirWin}\\daemon.mjs"

# Add to your agent's instructions file (system prompt, instructions.md, AGENTS.md, etc.):

## Elydora Audit Logging (MANDATORY)

${queueInstr}`;
        }

        // Step 5: log tool use — PRIMARY (queue write) + ALTERNATIVE (direct SDK)
        const logSteps: Record<'node' | 'python' | 'go', string> = {
          node: `5. After EVERY tool use, write a JSON file to the queue (PRIMARY) or call recordOperation directly (ALTERNATIVE):

PRIMARY — write to queue (daemon submits automatically):
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const queueDir = path.join(os.homedir(), '.elydora', '${creds.agentId}', 'queue');
fs.mkdirSync(queueDir, { recursive: true });
fs.writeFileSync(
  path.join(queueDir, \`\${Date.now()}-\${Math.random().toString(36).slice(2)}.json\`),
  JSON.stringify({ tool_name: toolName, tool_input: toolInput, session_id: sessionId }),
);

ALTERNATIVE — direct SDK call (faster, bypasses daemon):
import { homedir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
const { recordOperation } = await import(
  pathToFileURL(join(homedir(), '.elydora', '${creds.agentId}', 'client.mjs')).href
);
await recordOperation({
  operationType: 'ai.tool_use',
  subject: { session_id: sessionId },
  action: { tool: toolName },
  payload: { tool_name: toolName, tool_input: toolInput, session_id: sessionId },
});`,

          python: `5. After EVERY tool use, write a JSON file to the queue (PRIMARY) or call record_operation directly (ALTERNATIVE):

PRIMARY — write to queue (daemon submits automatically):
import json, time
from pathlib import Path

queue_dir = Path.home() / ".elydora" / "${creds.agentId}" / "queue"
queue_dir.mkdir(parents=True, exist_ok=True)
(queue_dir / f"{time.time_ns()}.json").write_text(json.dumps({
    "tool_name": tool_name,
    "tool_input": tool_input,
    "session_id": session_id,
}))

ALTERNATIVE — write to queue from a separate script (no daemon import needed):
import json, time, os

queue_dir = os.path.join(os.path.expanduser("~"), ".elydora", "${creds.agentId}", "queue")
os.makedirs(queue_dir, exist_ok=True)
payload = {"tool_name": tool_name, "tool_input": tool_input, "session_id": session_id}
filename = f"{int(time.time() * 1e9)}.json"
with open(os.path.join(queue_dir, filename), "w") as f:
    json.dump(payload, f)`,

          go: `5. After EVERY tool use, write a JSON file to the queue (PRIMARY) or use the Go SDK directly (ALTERNATIVE):

PRIMARY — write to queue (daemon submits automatically):
import (
    "encoding/json"
    "fmt"
    "os"
    "path/filepath"
    "time"
)

home, _ := os.UserHomeDir()
queueDir := filepath.Join(home, ".elydora", "${creds.agentId}", "queue")
os.MkdirAll(queueDir, 0755)
data, _ := json.Marshal(map[string]any{
    "tool_name": toolName, "tool_input": toolInput, "session_id": sessionId,
})
os.WriteFile(filepath.Join(queueDir, fmt.Sprintf("%d.json", time.Now().UnixNano())), data, 0644)

ALTERNATIVE — write to queue from Go (same approach, different entry point):
queueDir := filepath.Join(os.Getenv("HOME"), ".elydora", "${creds.agentId}", "queue")
payload := fmt.Sprintf(\`{"tool_name":"%s","tool_input":{},"session_id":"session-1"}\`, toolName)
filename := fmt.Sprintf("%d.json", time.Now().UnixNano())
os.WriteFile(filepath.Join(queueDir, filename), []byte(payload), 0644)`,
        };

        const verifyNote = `

6. Verify everything is working:
# Check daemon is running:
# macOS / Linux:   cat ${agentDir}/daemon.pid && echo "Daemon running"
# Windows:         Get-Content "${agentDirWin}\\daemon.pid"

# Check processed operations appear in ${agentDir}/processed/
# You can also verify in the Elydora console at ${typeof window !== 'undefined' ? window.location.origin : 'http://localhost:3000'}/operations`;

        return `${preamble}

${setupSteps[lang]}

${clientStep}

${daemonStep}

${instructionsStep}

${logSteps[lang]}${verifyNote}`;
      }

      const aiPrompt = !isSupported ? buildSdkAiPrompt(activeTab, selectedIntegration.id) : null;

      return (
        <div className="space-y-5">
          {/* Back navigation */}
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => {
                setSelectedIntegration(null);
                setActiveTab('node');
              }}
              className="flex items-center gap-1.5 font-mono text-[11px] text-ink-dim hover:text-ink transition-colors"
            >
              <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M10 3L5 8l5 5" />
              </svg>
              {t('agentRegistration.backToList')}
            </button>
            <div className="flex-1" />
            <div className="font-mono text-[10px] text-ink-dim uppercase tracking-wider">
              {t('agentRegistration.step', { current: 2, total: 2 })}
            </div>
          </div>

          {/* Selected integration header */}
          <div className="flex items-center gap-3">
            <div className={`w-8 h-8 border border-ink flex items-center justify-center ${isSupported ? 'bg-ink' : 'bg-surface'}`}>
              <span className={`font-mono text-[11px] font-bold ${isSupported ? 'text-[#EAEAE5]' : 'text-ink'}`}>
                {selectedIntegration.name.charAt(0)}
              </span>
            </div>
            <div className="flex-1 min-w-0">
              <div className="font-sans text-base font-semibold text-ink">{selectedIntegration.name}</div>
              <div className="font-mono text-[11px] text-ink-dim">{t('integrations.' + selectedIntegration.id)}</div>
            </div>
            {!isSupported && aiPrompt && (
              <button
                type="button"
                onClick={() => copyToClipboard(aiPrompt, 'ai-prompt')}
                className="shrink-0 flex items-center gap-1.5 px-3 py-1.5 border border-ink bg-ink text-[#EAEAE5] font-mono text-[10px] uppercase tracking-wider hover:bg-transparent hover:text-ink transition-colors"
              >
                <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
                  <path d="M4 4V2h10v10h-2M2 6h10v10H2z" />
                </svg>
                {copiedField === 'ai-prompt' ? t('common.copied') : t('agentRegistration.copyPrompt')}
              </button>
            )}
          </div>

          {/* AI prompt description for SDK integrations */}
          {!isSupported && (
            <div className="border border-border bg-surface p-3">
              <p className="font-mono text-[10px] text-ink-dim leading-relaxed">
                {t('agentRegistration.aiReadyPromptDesc')}
              </p>
            </div>
          )}

          {/* Language tabs */}
          <div className="flex border-b border-border mb-0">
            {(['node', 'python', 'go'] as const).map((tab) => (
              <button
                key={tab}
                type="button"
                onClick={() => setActiveTab(tab)}
                className={`px-4 py-2 font-mono text-[11px] uppercase tracking-wider border-b-2 transition-colors ${
                  activeTab === tab
                    ? 'border-ink text-ink'
                    : 'border-transparent text-ink-dim hover:text-ink'
                }`}
              >
                {tab === 'node' ? 'Node.js' : tab === 'python' ? 'Python' : 'Go'}
              </button>
            ))}
          </div>

          {/* ── Supported: single install command ── */}
          {isSupported && cliCmds && (
            <>
              <div className="font-mono text-[10px] text-ink-dim uppercase tracking-wider">
                {t('agentRegistration.install')}
              </div>
              <div className="relative">
                <pre className="p-4 bg-ink text-[#EAEAE5] font-mono text-[11px] leading-relaxed whitespace-pre-wrap break-all">
                  {cliCmds[activeTab]}
                </pre>
                <button
                  type="button"
                  onClick={() => copyToClipboard(cliCmds[activeTab], 'cli-cmd')}
                  className="absolute top-2 right-2 px-2 py-1 bg-[rgba(234,234,229,0.1)] text-[#EAEAE5] font-mono text-[9px] uppercase tracking-wider hover:bg-[rgba(234,234,229,0.2)] transition-colors"
                >
                  {copiedField === 'cli-cmd' ? t('common.copied') : t('common.copy')}
                </button>
              </div>
            </>
          )}

          {/* ── Unsupported: step-by-step SDK tutorial ── */}
          {!isSupported && steps && (
            <div className="space-y-4 max-h-[420px] overflow-y-auto pr-1">
              {steps.map((step, i) => (
                <div key={i} className="border border-border">
                  {/* Step header */}
                  <div className="flex items-start gap-3 p-3 bg-surface">
                    <div className="w-5 h-5 shrink-0 border border-ink flex items-center justify-center bg-ink mt-0.5">
                      <span className="font-mono text-[9px] font-bold text-[#EAEAE5]">{i + 1}</span>
                    </div>
                    <div className="min-w-0">
                      <div className="font-mono text-[12px] font-semibold text-ink">{step.title}</div>
                      <p className="font-mono text-[10px] text-ink-dim mt-0.5 leading-relaxed">{step.description}</p>
                    </div>
                  </div>
                  {/* Step code */}
                  <div className="relative">
                    <pre className="p-3 bg-ink text-[#EAEAE5] font-mono text-[10px] leading-relaxed overflow-x-auto">
                      {step.code}
                    </pre>
                    <button
                      type="button"
                      onClick={() => copyToClipboard(step.code, `step-${i}`)}
                      className="absolute top-1.5 right-1.5 px-2 py-0.5 bg-[rgba(234,234,229,0.1)] text-[#EAEAE5] font-mono text-[9px] uppercase tracking-wider hover:bg-[rgba(234,234,229,0.2)] transition-colors"
                    >
                      {copiedField === `step-${i}` ? t('common.copied') : t('common.copy')}
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Done */}
          <div className="flex items-center justify-end pt-2">
            <button
              type="button"
              onClick={onSuccess}
              className="btn-brutalist"
            >
              {t('agentRegistration.done')}
            </button>
          </div>
        </div>
      );
    }

    // Integration selector grid (no integration selected yet)
    return (
      <div className="space-y-5">
        {/* Back to credentials */}
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => setSuccessStep('credentials')}
            className="flex items-center gap-1.5 font-mono text-[11px] text-ink-dim hover:text-ink transition-colors"
          >
            <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M10 3L5 8l5 5" />
            </svg>
            {t('agentRegistration.backToList')}
          </button>
          <div className="flex-1" />
          <div className="font-mono text-[10px] text-ink-dim uppercase tracking-wider">
            {t('agentRegistration.step', { current: 2, total: 2 })}
          </div>
        </div>

        {/* Section header */}
        <div>
          <div className="font-sans text-base font-semibold text-ink">{t('agentRegistration.chooseIntegration')}</div>
          <p className="font-mono text-[11px] text-ink-dim mt-1">
            {t('agentRegistration.chooseIntegrationDesc')}
          </p>
        </div>

        {/* Supported integrations */}
        <div>
          <div className="font-mono text-[10px] text-ink-dim uppercase tracking-wider mb-2">
            {t('agentRegistration.supported')}
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            {supportedIntegrations.map((integration) => (
              <button
                key={integration.id}
                type="button"
                onClick={() => {
                  setSelectedIntegration(integration);
                  setActiveTab('node');
                  api.agents.update(creds.agentId, { integration_type: integration.id }).catch(() => {});
                }}
                className="text-left border border-border p-3 bg-surface hover:border-ink transition-colors group"
              >
                <div className="flex items-center gap-2 mb-1">
                  <div className="w-5 h-5 border border-ink flex items-center justify-center bg-ink">
                    <span className="font-mono text-[9px] font-bold text-[#EAEAE5]">
                      {integration.name.charAt(0)}
                    </span>
                  </div>
                  <span className="font-mono text-[12px] font-semibold text-ink">{integration.name}</span>
                </div>
                <div className="font-mono text-[10px] text-ink-dim">{t('integrations.' + integration.id)}</div>
              </button>
            ))}
          </div>
        </div>

        {/* SDK integrations */}
        <div>
          <div className="font-mono text-[10px] text-ink-dim uppercase tracking-wider mb-2">
            {t('agentRegistration.sdkIntegration')}
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            {sdkIntegrations.map((integration) => (
              <button
                key={integration.id}
                type="button"
                onClick={() => {
                  setSelectedIntegration(integration);
                  setActiveTab('node');
                  api.agents.update(creds.agentId, { integration_type: integration.id }).catch(() => {});
                }}
                className="text-left border border-border p-3 bg-surface hover:border-ink transition-colors group"
              >
                <div className="flex items-center gap-2 mb-1">
                  <div className="w-5 h-5 border border-border flex items-center justify-center bg-surface">
                    <span className="font-mono text-[9px] font-bold text-ink-dim">
                      {integration.name.charAt(0)}
                    </span>
                  </div>
                  <span className="font-mono text-[12px] font-semibold text-ink">{integration.name}</span>
                </div>
                <div className="font-mono text-[10px] text-ink-dim">{t('integrations.' + integration.id)}</div>
              </button>
            ))}
          </div>
        </div>

        {/* Skip */}
        <div className="flex items-center justify-end pt-2">
          <button
            type="button"
            onClick={onSuccess}
            className="btn-ghost"
          >
            {t('agentRegistration.done')}
          </button>
        </div>
      </div>
    );
  }

  // ─── Registration Form ────────────────────────────────────────────────
  return (
    <form onSubmit={handleSubmit} className="space-y-5">
      {error && (
        <div className="px-4 py-3 border border-red-300 bg-red-50 text-red-700 font-mono text-[12px]">
          {error}
        </div>
      )}

      <div>
        <label className="section-label block mb-1.5">{t('agentRegistration.displayName')}</label>
        <input
          type="text"
          value={displayName}
          onChange={(e) => setDisplayName(e.target.value)}
          placeholder={t('agentRegistration.displayNamePlaceholder')}
          className="w-full px-3 py-2 bg-transparent border border-border font-mono text-[13px] text-ink placeholder:text-ink-dim focus:outline-none focus:border-ink transition-colors"
          required
          autoFocus
        />
      </div>

      <div>
        <label className="section-label block mb-1.5">{t('agentRegistration.responsibleEntity')}</label>
        <input
          type="text"
          value={responsibleEntity}
          onChange={(e) => setResponsibleEntity(e.target.value)}
          placeholder={t('agentRegistration.responsibleEntityPlaceholder')}
          className="w-full px-3 py-2 bg-transparent border border-border font-mono text-[13px] text-ink placeholder:text-ink-dim focus:outline-none focus:border-ink transition-colors"
        />
      </div>

      <div className="flex items-center justify-end gap-3 pt-2">
        <button type="button" onClick={onCancel} className="btn-ghost">
          {t('common.cancel')}
        </button>
        <button type="submit" className="btn-brutalist" disabled={submitting}>
          {submitting ? t('agentRegistration.submitting') : t('agentRegistration.submit')}
        </button>
      </div>
    </form>
  );
}

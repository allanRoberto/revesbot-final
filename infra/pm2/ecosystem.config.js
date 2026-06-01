const path = require("path");

const stage = process.env.DEPLOY_STAGE;

if (!["develop", "main"].includes(stage)) {
  throw new Error(
    "DEPLOY_STAGE must be one of: develop, main"
  );
}

const repoRoot = process.env.REPO_ROOT || path.resolve(__dirname, "../..");
const pythonBin = process.env.PYTHON_BIN || path.join(repoRoot, ".venv", "bin", "python");
const isDevelop = stage === "develop";
const suffix = isDevelop ? "dev" : "prod";
const apiPort = process.env.API_PORT || (isDevelop ? "8081" : "8080");
const authApiPort = process.env.AUTH_API_PORT || (isDevelop ? "3091" : "3090");
const nodeEnv = isDevelop ? "development" : "production";

module.exports = {
  apps: [
    {
      name: `api-${suffix}`,
      cwd: repoRoot,
      script: "apps/api/start.py",
      interpreter: pythonBin,
      autorestart: true,
      max_restarts: 10,
      restart_delay: 3000,
      kill_timeout: 5000,
      time: true,
      env: {
        DEPLOY_STAGE: stage,
        PORT: apiPort,
        PYTHONUNBUFFERED: "1",
      },
    },
    {
      name: `auth-api-${suffix}`,
      cwd: path.join(repoRoot, "apps", "auth_api"),
      script: "dist/main.js",
      interpreter: "node",
      autorestart: true,
      max_restarts: 10,
      restart_delay: 3000,
      kill_timeout: 5000,
      time: true,
      env: {
        DEPLOY_STAGE: stage,
        NODE_ENV: nodeEnv,
        PORT: authApiPort,
      },
    },
    {
      name: `collector-${suffix}`,
      cwd: path.join(repoRoot, "apps", "collector"),
      script: "main.py",
      interpreter: pythonBin,
      autorestart: true,
      max_restarts: 10,
      restart_delay: 3000,
      kill_timeout: 5000,
      time: true,
      env: {
        DEPLOY_STAGE: stage,
        PYTHONUNBUFFERED: "1",
      },
    },
    {
      name: `triplet-maintainer-${suffix}`,
      cwd: repoRoot,
      script: "apps/monitoring/scripts/triplet_maintainer.py",
      interpreter: pythonBin,
      autorestart: true,
      max_restarts: 10,
      restart_delay: 3000,
      kill_timeout: 5000,
      time: true,
      env: {
        DEPLOY_STAGE: stage,
        PYTHONUNBUFFERED: "1",
        TRIPLET_POLL_SECONDS: "2",
      },
    },
    {
      name: `triplet-terminal-3pos-${suffix}`,
      cwd: repoRoot,
      script: "apps/monitoring/scripts/triplet_terminal_worker.py",
      interpreter: pythonBin,
      autorestart: true,
      max_restarts: 10,
      restart_delay: 3000,
      kill_timeout: 5000,
      time: true,
      env: {
        DEPLOY_STAGE: stage,
        PYTHONUNBUFFERED: "1",
        TRIPLET_TERMINAL_ROULETTE_IDS: "pragmatic-auto-roulette,pragmatic-brazilian-roulette,pragmatic-mega-roulette",
        TRIPLET_TERMINAL_POSITIONS: "3",
        TRIPLET_TERMINAL_SPINS: "500",
        TRIPLET_TERMINAL_PRE_WINDOW: "3",
        TRIPLET_TERMINAL_MAX_ATTEMPTS: "4",
        TRIPLET_TERMINAL_MAX_POST: "20",
        TRIPLET_TERMINAL_MIN_OCCUR: "3",
        TRIPLET_TERMINAL_MIN_SCORE: "3",
        TRIPLET_TERMINAL_NEIGHBOR_SPAN: "1",
        TRIPLET_TERMINAL_POLL_SECONDS: "2",
        TRIPLET_TERMINAL_BLOCKED_TERMINALS: "0,1,7",
      },
    },
    {
      name: `quadruplet-terminal-3pos-${suffix}`,
      cwd: repoRoot,
      script: "apps/monitoring/scripts/quadruplet_terminal_worker.py",
      interpreter: pythonBin,
      autorestart: true,
      max_restarts: 10,
      restart_delay: 3000,
      kill_timeout: 5000,
      time: true,
      env: {
        DEPLOY_STAGE: stage,
        PYTHONUNBUFFERED: "1",
        QUAD_TERMINAL_ROULETTE_IDS: "pragmatic-auto-roulette,pragmatic-brazilian-roulette,pragmatic-mega-roulette",
        QUAD_TERMINAL_POSITIONS: "3",
        QUAD_TERMINAL_SPINS: "500",
        QUAD_TERMINAL_PRE_WINDOW: "4",
        QUAD_TERMINAL_MAX_ATTEMPTS: "4",
        QUAD_TERMINAL_MAX_POST: "20",
        QUAD_TERMINAL_MIN_OCCUR: "3",
        QUAD_TERMINAL_MIN_SCORE: "3",
        QUAD_TERMINAL_NEIGHBOR_SPAN: "1",
        QUAD_TERMINAL_POLL_SECONDS: "2",
        QUAD_TERMINAL_BLOCKED_TERMINALS: "0,1,7",
      },
    },
    {
      name: `numeros-fortes-${suffix}`,
      cwd: repoRoot,
      script: "apps/monitoring/scripts/numeros_fortes_worker.py",
      interpreter: pythonBin,
      autorestart: true,
      max_restarts: 10,
      restart_delay: 3000,
      kill_timeout: 5000,
      time: true,
      env: {
        DEPLOY_STAGE: stage,
        PYTHONUNBUFFERED: "1",
        NUMEROS_FORTES_ROULETTE_IDS: "pragmatic-auto-roulette,pragmatic-brazilian-roulette",
        NUMEROS_FORTES_SPINS: "500",
        NUMEROS_FORTES_COUNT: "13",
        NUMEROS_FORTES_GATILHOS_MAX: "8",
        NUMEROS_FORTES_RECENT_WINDOW: "50",
        NUMEROS_FORTES_MAX_ATTEMPTS: "4",
        NUMEROS_FORTES_POLL_SECONDS: "2",
        // Gate de qualidade (filtros de entrada + porteiro de regime).
        // "flag" = sombra: cria todos os sinais e só anota `quality` (não muda volume).
        // Para passar a ENFORCAR, troque GATE_MODE para "block".
        NUMEROS_FORTES_GATE_ENABLED: "1",
        NUMEROS_FORTES_GATE_MODE: "flag",
        NUMEROS_FORTES_BLOCK_TERMINALS: "2",
        NUMEROS_FORTES_MIN_INVERSION_HITS: "2",
        NUMEROS_FORTES_REGIME_ENABLED: "1",
        NUMEROS_FORTES_REGIME_WINDOW: "15",
        NUMEROS_FORTES_REGIME_MIN_SAMPLE: "8",
        NUMEROS_FORTES_REGIME_COLD_WR: "0.80",
        NUMEROS_FORTES_REGIME_SUPPRESS: "0",
      },
    },
    {
      name: `numeros-fortes-inversao-${suffix}`,
      cwd: repoRoot,
      script: "apps/monitoring/scripts/numeros_fortes_inversao_worker.py",
      interpreter: pythonBin,
      autorestart: true,
      max_restarts: 10,
      restart_delay: 3000,
      kill_timeout: 5000,
      time: true,
      env: {
        DEPLOY_STAGE: stage,
        PYTHONUNBUFFERED: "1",
        NUMEROS_FORTES_INVERSAO_ROULETTE_IDS: "pragmatic-auto-roulette,pragmatic-brazilian-roulette",
        NUMEROS_FORTES_INVERSAO_SPINS: "500",
        NUMEROS_FORTES_INVERSAO_COUNT: "13",
        NUMEROS_FORTES_INVERSAO_GATILHOS_MAX: "8",
        NUMEROS_FORTES_INVERSAO_RECENT_WINDOW: "50",
        NUMEROS_FORTES_INVERSAO_MAX_ATTEMPTS: "4",
        NUMEROS_FORTES_INVERSAO_POLL_SECONDS: "2",
        NUMEROS_FORTES_INVERSAO_TRIGGER_MIN: "3",
        NUMEROS_FORTES_INVERSAO_TRIGGER_WINDOW: "5",
        NUMEROS_FORTES_INVERSAO_POST_ROUNDS: "10",
        NUMEROS_FORTES_INVERSAO_INVERSION_WINDOW: "5",
      },
    },
  ],
};

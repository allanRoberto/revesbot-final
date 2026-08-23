const path = require("path");

const currentRoot = process.env.REVESBOT_PATTERNS_CURRENT || "/var/www/revesbot/patterns-current";
const patternKeys = (process.env.PATTERN_KEYS || "nera,last_hope")
  .split(",")
  .map((key) => key.trim())
  .filter(Boolean);

const processes = patternKeys.map((patternKey) => ({
  name: `pattern-${patternKey.replaceAll("_", "-")}-prod`,
  cwd: currentRoot,
  script: "apps/monitoring/patterns/__main__.py",
  args: ["--pattern", patternKey],
  interpreter: path.join(currentRoot, ".venv", "bin", "python"),
  instances: 1,
  autorestart: true,
  exp_backoff_restart_delay: 1000,
  restart_delay: 2000,
  kill_timeout: 15000,
  max_memory_restart: "512M",
  time: true,
  env: {
    PYTHONUNBUFFERED: "1",
    MONGO_URL: process.env.MONGO_URL,
    MONGO_DATABASE: process.env.MONGO_DATABASE || "roleta_db",
    REDIS_CONNECT: process.env.REDIS_CONNECT,
    LOG_LEVEL: process.env.LOG_LEVEL || "INFO",
    PATTERN_POLL_SECONDS: process.env.PATTERN_POLL_SECONDS || "1",
    PATTERN_BATCH_SIZE: process.env.PATTERN_BATCH_SIZE || "200",
    PATTERN_GAP_SECONDS: process.env.PATTERN_GAP_SECONDS || "300",
    PATTERN_LEASE_SECONDS: process.env.PATTERN_LEASE_SECONDS || "30",
    PATTERN_PROJECTION_SECONDS: process.env.PATTERN_PROJECTION_SECONDS || "30",
  },
}));

module.exports = { apps: processes };

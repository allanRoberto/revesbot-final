const path = require("path");

const currentRoot = process.env.REVESBOT_CURRENT || "/var/www/revesbot/current";
const collectorDir = path.join(currentRoot, "apps", "collector");

module.exports = {
  apps: [
    {
      name: process.env.COLLECTOR_PROCESS_NAME || "collector-pragmatic-test",
      cwd: collectorDir,
      script: "main.py",
      interpreter: path.join(currentRoot, ".venv", "bin", "python"),
      autorestart: true,
      exp_backoff_restart_delay: 1000,
      restart_delay: 2000,
      kill_timeout: 10000,
      max_memory_restart: "1500M",
      time: true,
      env: {
        PYTHONUNBUFFERED: "1",
        DEPLOY_STAGE: process.env.DEPLOY_STAGE || "collector-test",
        MONGO_URL: process.env.MONGO_URL,
        MONGO_DATABASE: process.env.MONGO_DATABASE,
        MONGO_COLLECTION: process.env.MONGO_COLLECTION,
        REDIS_CONNECT: process.env.REDIS_CONNECT,
        RESULT_CHANNEL: process.env.RESULT_CHANNEL,
        PRAGMATIC_CASINO_ID: process.env.PRAGMATIC_CASINO_ID,
        PRAGMATIC_SUBSCRIBE_KEYS: process.env.PRAGMATIC_SUBSCRIBE_KEYS,
        COLLECTOR_HEALTH_HOST: process.env.COLLECTOR_HEALTH_HOST,
        COLLECTOR_HEALTH_PORT: process.env.COLLECTOR_HEALTH_PORT,
        COLLECTOR_WS_STALE_SECONDS: process.env.COLLECTOR_WS_STALE_SECONDS,
        COLLECTOR_RESULT_STALE_SECONDS: process.env.COLLECTOR_RESULT_STALE_SECONDS,
        COLLECTOR_STARTUP_GRACE_SECONDS: process.env.COLLECTOR_STARTUP_GRACE_SECONDS,
        COLLECTOR_WATCHDOG_INTERVAL_SECONDS: process.env.COLLECTOR_WATCHDOG_INTERVAL_SECONDS,
        COLLECTOR_WATCHDOG_FAILURES: process.env.COLLECTOR_WATCHDOG_FAILURES,
        COLLECTOR_WATCHDOG_EXIT_ENABLED: process.env.COLLECTOR_WATCHDOG_EXIT_ENABLED,
        COLLECTOR_RETENTION_LIMIT: process.env.COLLECTOR_RETENTION_LIMIT,
        COLLECTOR_RETENTION_INTERVAL_SECONDS: process.env.COLLECTOR_RETENTION_INTERVAL_SECONDS,
        LOG_LEVEL: process.env.LOG_LEVEL,
      },
    },
  ],
};

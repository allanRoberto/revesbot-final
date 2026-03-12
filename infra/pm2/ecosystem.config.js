module.exports = {
  apps: [
    {
      name: "api",
      cwd: "./apps/api",
      script: "start.py",
      interpreter: "python3",
      env: {
        PORT: "8080"
      }
    },
    {
      name: "collector",
      cwd: "./apps/collector",
      script: "main.py",
      interpreter: "python3"
    },
    {
      name: "signals",
      cwd: "./apps/signals",
      script: "main.py",
      interpreter: "python3"
    },
    {
      name: "monitoring",
      cwd: "./apps/monitoring",
      script: "main.py",
      interpreter: "python3",
      env: {
        PYTHONPATH: "."
      }
    },
    {
      name: "auth_api",
      cwd: "./apps/auth_api",
      script: "node",
      args: "dist/main.js",
      env: {
        NODE_ENV: "production"
      }
    },
    {
      name: "bot_automatico",
      cwd: "./apps/bot_automatico",
      script: "main.js",
      interpreter: "node",
      env: {
        NODE_ENV: "production"
      }
    }
  ]
};

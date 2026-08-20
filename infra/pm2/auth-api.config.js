const path = require('path');

const currentRoot = process.env.REVESBOT_AUTH_CURRENT || '/var/www/revesbot/auth-current';

module.exports = {
  apps: [
    {
      name: 'revesbot-auth',
      cwd: path.join(currentRoot, 'apps', 'auth_api'),
      script: 'dist/main.js',
      interpreter: 'node',
      instances: 1,
      autorestart: true,
      exp_backoff_restart_delay: 1000,
      restart_delay: 2000,
      kill_timeout: 10000,
      max_memory_restart: '500M',
      time: true,
      env: {
        NODE_ENV: 'production',
        HOST: process.env.AUTH_HOST || '127.0.0.1',
        PORT: process.env.AUTH_PORT || '3090',
        APP_ORIGINS: process.env.APP_ORIGINS || 'https://app.revesbot.com.br',
      },
    },
  ],
};

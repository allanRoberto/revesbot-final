import 'dotenv/config';
import express from 'express';
import cors from 'cors';
import cookieParser from 'cookie-parser';
import apiRoutes from './routes';

const app = express();
const allowedOrigins = new Set(
  (process.env.APP_ORIGINS || 'https://app.revesbot.com.br')
    .split(',')
    .map((origin) => origin.trim())
    .filter(Boolean),
);

app.set('trust proxy', 1);
app.disable('x-powered-by');
app.use(cors({
  credentials: true,
  origin(origin, callback) {
    callback(null, !origin || allowedOrigins.has(origin));
  },
}));
app.use(express.json({ limit: '1mb' }));
app.use(express.urlencoded({ extended: true, limit: '1mb' }));
app.use(cookieParser());

app.use('/', apiRoutes);
app.use('/api', apiRoutes);

const PORT = Number(process.env.PORT || 3090);
const HOST = process.env.HOST || '127.0.0.1';
const server = app.listen(PORT, HOST, () => {
  console.log(`Auth API rodando em http://${HOST}:${PORT}`);
});

function shutdown(signal: string) {
  console.log(`[shutdown] ${signal}`);
  server.close((error) => {
    if (error) {
      console.error('[shutdown]', error);
      process.exitCode = 1;
    }
  });
}

process.on('SIGTERM', () => shutdown('SIGTERM'));
process.on('SIGINT', () => shutdown('SIGINT'));

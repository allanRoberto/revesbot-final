// src/index.js
import 'dotenv/config';           // carrega e executa o .config() automaticamente
import express from 'express';
//import { createServer } from 'http';
import cors from 'cors';
import cookieParser from 'cookie-parser';
import apiRoutes from './routes/apiRoutes.js';
//import { setupWebsocket } from './websocket.js';

//import redisClient from './lib/redisClient.js';

const app = express();

// 🔧 Middlewares
app.use(cors({ origin: true, credentials: true }));
app.use(express.json({ limit: '10mb' }));
app.use(express.urlencoded({ extended: true, limit: '10mb' }));
app.use(cookieParser());

// 📦 Rotas REST
app.use('/api', apiRoutes);

// 🔗 HTTP + WS num mesmo server
//const server = createServer(app);


// ⚙️ Configura WebSocket
//setupWebsocket(server, redisClient);

// 📡 Start
const PORT = process.env.PORT || 3090;
app.listen(PORT, () => {
  console.log(`Server HTTP e WS rodando na porta ${PORT}`);
});
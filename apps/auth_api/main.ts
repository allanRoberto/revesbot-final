// src/index.js
import 'dotenv/config';   
import express from 'express';
import axios from 'axios';
import { createServer } from 'http';
import WebSocket, { WebSocketServer } from 'ws';
import puppeteer from 'puppeteer';
import { randomUUID } from 'crypto';  
import url from 'url';

import cors from 'cors';
import cookieParser from 'cookie-parser';
import apiRoutes from './routes';


const app = express();


// 🔧 Middlewares
app.use(cors({ origin: true, credentials: true }));
app.use(express.json({ limit: '10mb' }));
app.use(express.urlencoded({ extended: true, limit: '10mb' }));
app.use(cookieParser());

// 📦 Rotas REST
app.use('/', apiRoutes);
app.use('/api', apiRoutes);

const server = createServer(app);
const wss = new WebSocketServer({ server });

wss.on('connection', async (ws, req:any) => {
  try {
    const parsed = url.parse(req.url, true);
    const { token, slug, gameId } = parsed.query || {};

    if (!token || !slug || !gameId) {
      console.warn('[ws] Conexão sem token/slug/gameId. Fechando.');
      ws.close(1008, 'Parâmetros obrigatórios ausentes.');
      return;
    }


    console.log(
      `[ws] Novo cliente conectado. token=${token} slug=${slug} gameId=${gameId}`,
    );


    // Quando o cliente fechar, removemos da lista de clientes dessa mesa
    ws.on('close', () => {
      console.log(
        `[ws] Cliente desconectado. slug=${slug} gameId=${gameId}`,
      );
    });

    ws.on('error', (err) => {
      console.error('[ws] Erro no cliente WS:', err.message);
    });

    
  } catch (err) {
    console.error('[ws] Erro na conexão WS:', err);
    try {
      ws.close(1011, 'Erro interno no servidor.');
    } catch (_) {}
  }
});



// 📡 Start
const PORT = process.env.PORT || 3090;
app.listen(PORT, () => {
  console.log(`Server HTTP e WS rodando na porta ${PORT}`);
})

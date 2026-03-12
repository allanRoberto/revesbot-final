const Redis = require('ioredis');
const WebSocket = require('ws');
const puppeteer = require('puppeteer');
const axios = require('axios');

// ============================
// CONFIGURAÇÕES
// ============================
const CONFIG = {
    email: 'allan.rsti@gmail.com',
    password: '419300@Al',
    valorBase: 0.5,
    usarMartingale: false,
    
    // Filtros
    apenasFirstEntry: false,
    maxPassedSpins: 999,  // Aceita todos
    minPassedSpins: 0,    // Aceita todos
    
    // Limites de processamento
    maxSimultaneousSignals: 2, // Processar até 5 sinais simultâneos
    preventDuplicateTables: true, // Permite múltiplas mesas simultaneamente
    
    // Cache
    cacheTimeout: 5 * 60 * 1000,
    reutilizarConexao: true,
    
    // Redis Streams
    redisUrl: 'redis://:09T6iVOEmt7p0lEEXiRZATotvS70fPzK@45.179.88.134:6379',
    consumerGroup: 'bots',
    consumerName: `bot-${Date.now()}`,
    
    // Timeouts
    signalTimeout: 5 * 60 * 1000,
};

// ============================
// REDIS CLIENT
// ============================
const redis = new Redis(CONFIG.redisUrl);

// ============================
// CONTROLE GLOBAL
// ============================
const activeTables = new Set();
const activeSignals = new Map();
const updateCallbacks = new Map();

function canProcessSignal(signal) {
    if (activeSignals.size >= CONFIG.maxSimultaneousSignals) {
        return false;
    }
    
    if (CONFIG.preventDuplicateTables && activeTables.has(signal.roulette_name)) {
        return false;
    }
    
    return true;
}

function registerSignal(signal) {
    activeSignals.set(signal.id, {
        mesa: signal.roulette_name,
        startTime: Date.now()
    });
    activeTables.add(signal.roulette_name);
    
    console.log(`📊 Sinais ativos: ${activeSignals.size}/${CONFIG.maxSimultaneousSignals}`);
    console.log(`📊 Mesas ativas: [${Array.from(activeTables).join(', ')}]`);
}

function unregisterSignal(signalId) {
    const info = activeSignals.get(signalId);
    if (info) {
        activeTables.delete(info.mesa);
        activeSignals.delete(signalId);
        updateCallbacks.delete(signalId);
        
        const duration = ((Date.now() - info.startTime) / 1000).toFixed(1);
        console.log(`✔ Sinal ${signalId} liberado após ${duration}s`);
        console.log(`📊 Sinais ativos restantes: ${activeSignals.size}/${CONFIG.maxSimultaneousSignals}`);
    }
}

// ============================
// SISTEMA DE CACHE
// ============================
class AuthCache {
    constructor() {
        this.token = null;
        this.tokenTimestamp = null;
        this.wsUrls = new Map();
    }
    
    isTokenValid() {
        if (!this.token || !this.tokenTimestamp) return false;
        const elapsed = Date.now() - this.tokenTimestamp;
        return elapsed < CONFIG.cacheTimeout;
    }
    
    setToken(token) {
        this.token = token;
        this.tokenTimestamp = Date.now();
        console.log('🔑 Token salvo no cache');
    }
    
    getToken() {
        if (this.isTokenValid()) {
            return this.token;
        }
        this.token = null;
        this.tokenTimestamp = null;
        return null;
    }
    
    setWsUrl(gameId, url) {
        this.wsUrls.set(gameId, {
            url: url,
            timestamp: Date.now()
        });
    }
    
    getWsUrl(gameId) {
        const cached = this.wsUrls.get(gameId);
        if (cached) {
            const elapsed = Date.now() - cached.timestamp;
            if (elapsed < CONFIG.cacheTimeout) {
                return cached.url;
            }
            this.wsUrls.delete(gameId);
        }
        return null;
    }
}

const authCache = new AuthCache();

// ============================
// COOKIE MANAGER
// ============================
class CookieManager {
    constructor() {
        this.cookies = {};
    }
    
    extractCookies(setCookieHeaders) {
        if (!setCookieHeaders) return;
        const cookieArray = Array.isArray(setCookieHeaders) ? setCookieHeaders : [setCookieHeaders];
        cookieArray.forEach(cookie => {
            const [nameValue] = cookie.split(';');
            const [name, value] = nameValue.split('=');
            this.cookies[name.trim()] = value ? value.trim() : '';
        });
    }
    
    getCookie(name) {
        return this.cookies[name];
    }
}

// ============================
// LOGIN
// ============================
async function loginAndGetToken(email, password, forceNew = false) {
    if (!forceNew) {
        const cachedToken = authCache.getToken();
        if (cachedToken) {
            return { token: cachedToken, fromCache: true };
        }
    }
    
    console.log('🔐 Realizando novo login...');
    const response = await axios.post(
        "https://auth.revesbot.com.br/api/auth/login",
        { email, password },
        {
            headers: {
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            }
        }
    );
    
    const cookieManager = new CookieManager();
    cookieManager.extractCookies(response.headers['set-cookie']);
    const token = cookieManager.getCookie('bookmaker_token');
    
    if (!token) throw new Error('Token não encontrado');
    
    authCache.setToken(token);
    return { token, fromCache: false };
}

// ============================
// PARSERS
// ============================
function parseBetsOpenMessage(xmlMessage) {
    const gameMatch = xmlMessage.match(/game="([^"]+)"/);
    const tableMatch = xmlMessage.match(/table="([^"]+)"/);
    return (gameMatch && tableMatch) ? { game: gameMatch[1], table: tableMatch[1] } : null;
}

function generateChecksumTimestamp() {
    return Date.now().toString();
}

function sendBets(ws, gameInfo, signal, valorAposta) {
    const checksum = generateChecksumTimestamp();
    const betsXML = signal.bets.map(num => {
        let betCode = Number(num) == 0 ? 2 : Number(num) + 3;
        return `<bet amt="${valorAposta}" bc="${betCode}" ck="${checksum}" />`;
    }).join("");
    
    const message =
        `<command channel="table-${gameInfo.table}" >` +
        `<lpbet gm="roulette_desktop" gId="${gameInfo.game}" uId="ppc1735139140386" ck="${checksum}">` +
        betsXML +
        `</lpbet></command>`;
    
    console.log(`🎲 Apostando em ${signal.bets.join(', ')} | Valor: ${valorAposta} centavos`);
    ws.send(message);
}

// ============================
// WEBSOCKET URL
// ============================
async function getWebSocketUrl(gameId, auth) {
    const cachedUrl = authCache.getWsUrl(gameId);
    if (cachedUrl && CONFIG.reutilizarConexao) {
        return cachedUrl;
    }
    
    console.log('🔗 Obtendo nova URL do WebSocket...');
    const response = await axios.get(
        `https://auth.revesbot.com.br/api/start-game/${gameId}`,
        { headers: { 'Cookie': `bookmaker_token=${auth.token}` } }
    );
    
    if (!response.data.success || !response.data.link) {
        throw new Error('Falha ao iniciar o jogo');
    }
    
    const wsUrl = await getWebSocketUrlWithPuppeteer(response.data.link);
    authCache.setWsUrl(gameId, wsUrl);
    return wsUrl;
}

async function getWebSocketUrlWithPuppeteer(gameLink) {
    const browser = await puppeteer.launch({ 
        headless: true,
        args: ['--no-sandbox', '--disable-setuid-sandbox']
    });
    
    try {
        const page = await browser.newPage();
        await page.setUserAgent('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36');
        
        const webSocketUrls = [];
        
        await page.evaluateOnNewDocument(() => {
            const originalWebSocket = window.WebSocket;
            window.WebSocket = new Proxy(originalWebSocket, {
                construct(target, args) {
                    const url = args[0];
                    console.log('WS_INTERCEPTED:', url);
                    window.__wsUrls = window.__wsUrls || [];
                    window.__wsUrls.push(url);
                    return new target(...args);
                }
            });
        });
        
        page.on('console', msg => {
            const text = msg.text();
            if (text.includes('WS_INTERCEPTED:')) {
                const url = text.split('WS_INTERCEPTED:')[1].trim();
                webSocketUrls.push(url);
            }
        });
        
        page.on('websocket', ws => {
            webSocketUrls.push(ws.url());
        });
        
        await page.goto(gameLink, { waitUntil: 'networkidle2', timeout: 60000 });
        await new Promise(resolve => setTimeout(resolve, 3000));
        
        const capturedUrls = await page.evaluate(() => window.__wsUrls || []);
        const allUrls = [...new Set([...capturedUrls, ...webSocketUrls])];
        
        if (allUrls.length > 0) {
            const pragmaticUrl = allUrls.find(url => 
                url.includes('pragmatic') || url.includes('livecasino') || url.includes('game')
            );
            return pragmaticUrl || allUrls[0];
        }
        
        throw new Error('WebSocket URL não encontrada');
    } finally {
        await browser.close();
    }
}

// ============================
// GALE SESSION
// ============================
class GaleSession {
    constructor(signal) {
        this.signal = signal;
        this.signalId = signal.id;
        this.tentativasMaximas = signal.gales || 2;
        this.tentativasJaPassadas = signal.passed_spins || 0;
        this.tentativasRestantes = Math.max(0, this.tentativasMaximas - this.tentativasJaPassadas);
        this.tentativaAtual = 0;
        this.ganhou = false;
        this.sessaoFinalizada = false;
        this.valorAtual = CONFIG.valorBase;
        this.resultados = [];
        
        console.log(`\n📋 [GALE SESSION] Inicializada:`);
        console.log(`   tentativasMaximas: ${this.tentativasMaximas}`);
        console.log(`   tentativasJaPassadas: ${this.tentativasJaPassadas}`);
        console.log(`   tentativasRestantes: ${this.tentativasRestantes}`);
        console.log(`   tentativaAtual: ${this.tentativaAtual}`);
    }
    
    podeTentar() {
        const resultado = !this.ganhou && 
               !this.sessaoFinalizada && 
               this.tentativaAtual < this.tentativasRestantes;
        
        console.log(`\n🔍 [podeTentar] Verificação:`);
        console.log(`   ganhou: ${this.ganhou}`);
        console.log(`   sessaoFinalizada: ${this.sessaoFinalizada}`);
        console.log(`   tentativaAtual: ${this.tentativaAtual}`);
        console.log(`   tentativasRestantes: ${this.tentativasRestantes}`);
        console.log(`   RESULTADO: ${resultado}`);
        
        return resultado;
    }
    
    registrarTentativa(venceu, valor) {
        console.log(`\n📝 [registrarTentativa] ANTES:`);
        console.log(`   tentativaAtual: ${this.tentativaAtual}`);
        console.log(`   venceu: ${venceu}`);
        
        this.tentativaAtual++;
        this.resultados.push({
            tentativa: this.tentativaAtual,
            venceu: venceu,
            valor: valor
        });
        
        if (venceu) {
            this.ganhou = true;
            this.sessaoFinalizada = true;
            console.log(`✅ GANHOU na tentativa ${this.tentativaAtual} de ${this.tentativasRestantes}`);
        } else {
            if (this.tentativaAtual >= this.tentativasRestantes) {
                this.sessaoFinalizada = true;
                console.log(`❌ Esgotou as ${this.tentativasRestantes} tentativas`);
            } else {
                if (CONFIG.usarMartingale) {
                    this.valorAtual = this.valorAtual * 2;
                }
                console.log(`⚠️ Perdeu tentativa ${this.tentativaAtual}/${this.tentativasRestantes}`);
            }
        }
        
        console.log(`\n📝 [registrarTentativa] DEPOIS:`);
        console.log(`   tentativaAtual: ${this.tentativaAtual}`);
        console.log(`   ganhou: ${this.ganhou}`);
        console.log(`   sessaoFinalizada: ${this.sessaoFinalizada}`);
        console.log(`   valorAtual: ${this.valorAtual}`);
    }
}

// ============================
// CONSUMIDOR DE UPDATES (Event-driven)
// ============================
async function startUpdatesConsumer() {
    console.log('🔄 Iniciando consumidor de atualizações de sinais...\n');
    
    while (true) {
        try {
            const results = await redis.xreadgroup(
                'GROUP', CONFIG.consumerGroup, CONFIG.consumerName,
                'BLOCK', 1000,
                'COUNT', 10,
                'STREAMS', 'streams:signals:updates', '>'
            );
            
            if (!results) continue;
            
            for (const [stream, messages] of results) {
                for (const [messageId, fields] of messages) {
                    try {
                        const fieldObj = {};
                        for (let i = 0; i < fields.length; i += 2) {
                            fieldObj[fields[i]] = fields[i + 1];
                        }
                        
                        const signalData = JSON.parse(fieldObj.data);
                        
                        console.log(`\n📥 [STREAM UPDATE] Recebido:`);
                        console.log(`   signal_id: ${signalData.id}`);
                        console.log(`   status: ${signalData.status}`);
                        console.log(`   attempts: ${signalData.attempts}`);
                        console.log(`   roulette: ${signalData.roulette_name}`);
                        
                        // Verificar se temos callback
                        const callback = updateCallbacks.get(signalData.id);
                        
                        console.log(`   callback existe: ${!!callback}`);
                        console.log(`   total callbacks: ${updateCallbacks.size}`);
                       
                        
                        if (callback) {
                            console.log(`   ✅ Executando callback...`);
                            callback(signalData);
                        } else {
                            console.log(`   ⚠️ Callback não encontrado para signal ${signalData.id}`);
                        }
                        
                        await redis.xack('streams:signals:updates', CONFIG.consumerGroup, messageId);
                        
                    } catch (err) {
                        console.error('❌ Erro ao processar update:', err.message);
                        await redis.xack('streams:signals:updates', CONFIG.consumerGroup, messageId);
                    }
                }
            }
        } catch (err) {
            console.error('❌ Erro no consumidor de updates:', err.message);
            await new Promise(resolve => setTimeout(resolve, 1000));
        }
    }
}

// ============================
// FUNÇÃO PRINCIPAL DE APOSTA
// ============================
async function fazerApostaComGales(signal) {
    const startTime = Date.now();
    const sessao = new GaleSession(signal);
    const signalId = signal.id;
    
    registerSignal(signal);
    
    console.log('\n' + '═'.repeat(50));
    console.log(`🚀 INICIANDO SESSÃO DE APOSTAS`);
    console.log(`🆔 Signal ID: ${signalId}`);
    console.log(`📊 Mesa: ${signal.roulette_name}`);
    console.log(`🎯 Números: ${signal.bets.join(', ')}`);
    console.log(`🎰 Tentativas restantes: ${sessao.tentativasRestantes}`);
    console.log('═'.repeat(50));
    
    if (sessao.tentativasRestantes === 0) {
        console.log('⚠️ Sinal expirado');
        unregisterSignal(signalId);
        return;
    }
    
    let ws = null;
    let gameId = null;
    let apostaEnviada = false;
    
    // ⭐⭐⭐ REGISTRAR CALLBACK IMEDIATAMENTE - ANTES DE QUALQUER COISA ⭐⭐⭐
    console.log(`\n🔗 Registrando callback para sinal ${signalId}...`);
    
    updateCallbacks.set(signalId, (updatedSignal) => {
        console.log(`\n🔔 [CALLBACK EXECUTADO] Signal: ${signalId}`);
        console.log(`   Status: ${updatedSignal.status}`);
        console.log(`   Attempts (Redis): ${updatedSignal.attempts}`);
        console.log(`   TentativaAtual (Local): ${sessao.tentativaAtual}`);
        console.log(`   apostaEnviada: ${apostaEnviada}`);
        console.log(`   Mesa: ${updatedSignal.roulette_name}`);
        
        // Se ainda está processando mas já passou uma rodada
        if (updatedSignal.status === 'processing' && updatedSignal.attempts > sessao.tentativaAtual) {
            const venceu = false;
            
            console.log(`\n⚠️ [CALLBACK] Rodada ${updatedSignal.attempts} PERDIDA`);
            console.log(`   Antes de registrar:`);
            console.log(`      tentativaAtual: ${sessao.tentativaAtual}`);
            console.log(`      apostaEnviada: ${apostaEnviada}`);
            
            sessao.registrarTentativa(venceu, 0);
            apostaEnviada = false;
            
            console.log(`\n   ✅ Depois de registrar:`);
            console.log(`      tentativaAtual: ${sessao.tentativaAtual}`);
            console.log(`      apostaEnviada: ${apostaEnviada}`);
            console.log(`      podeTentar(): ${sessao.podeTentar()}`);
            console.log(`      sessaoFinalizada: ${sessao.sessaoFinalizada}`);
            console.log(`      ganhou: ${sessao.ganhou}`);
            
            if (sessao.sessaoFinalizada) {
                console.log('\n❌ Esgotou todos os gales');
                if (ws) ws.close();
            } else {
                console.log(`\n🔄 Preparando tentativa ${sessao.tentativaAtual + 1}/${sessao.tentativasRestantes}...`);
                console.log(`   Aguardando próximo <betsopen>...\n`);
            }
            return;
        }
        
        // Se finalizou
        const statusFinalizados = ['win', 'lost', 'cancelled'];
        if (statusFinalizados.includes(updatedSignal.status)) {
            const venceu = updatedSignal.status === 'win';
            const cancelado = updatedSignal.status === 'cancelled';
            
            console.log(`\n🏁 [CALLBACK] Sinal FINALIZADO: ${updatedSignal.status}`);
            
            if (cancelado) {
                console.log('🚫 Aposta cancelada');
                if (ws) ws.close();
                return;
            }
            
            sessao.registrarTentativa(venceu, 0);
            
            console.log('\n' + '─'.repeat(50));
            console.log('📊 RESUMO DA SESSÃO:');
            console.log(`   Mesa: ${signal.roulette_name}`);
            console.log(`   Tentativas usadas: ${sessao.tentativaAtual}/${sessao.tentativasRestantes}`);
            console.log(`   Resultado: ${sessao.ganhou ? '✅ WIN' : '❌ LOSS'}`);
            console.log('─'.repeat(50) + '\n');
            
            if (ws) ws.close();
        }
    });
    
    console.log(`✅ Callback registrado! updateCallbacks.size = ${updateCallbacks.size}`);
    
    // Agora sim, começar o processo de aposta
    try {
        gameId = signal.roulette_url.split("/").pop();
        console.log(`\n🎯 Game ID: ${gameId}`);
        
        const auth = await loginAndGetToken(CONFIG.email, CONFIG.password);
        const urlGame = await getWebSocketUrl(gameId, auth);
        
        console.log('🔌 Conectando à mesa...\n');
        ws = new WebSocket(urlGame);
        
        ws.on('open', () => {
            console.log('✅ Conectado à mesa');
            console.log(`⏳ Aguardando abertura de apostas (Tentativa ${sessao.tentativaAtual + 1}/${sessao.tentativasRestantes})...\n`);
        });
        
        ws.on('message', async (data) => {
            const message = data.toString();
            
            // Log de TODAS mensagens relevantes
            if (message.includes('<betsopen') || message.includes('<betsclosingsoon')) {
                console.log(`\n🎰 [WS MESSAGE] Apostas abertas detectadas!`);
                console.log(`   Timestamp: ${new Date().toISOString()}`);
                console.log(`   apostaEnviada: ${apostaEnviada}`);
                console.log(`   tentativaAtual: ${sessao.tentativaAtual}`);
                console.log(`   tentativasRestantes: ${sessao.tentativasRestantes}`);
                console.log(`   ganhou: ${sessao.ganhou}`);
                console.log(`   sessaoFinalizada: ${sessao.sessaoFinalizada}`);
                console.log(`   podeTentar(): ${sessao.podeTentar()}`);
            }
            
            if ((message.includes('<betsopen') || message.includes('<betsclosingsoon')) 
                && !apostaEnviada 
                && sessao.podeTentar()) {
                
                const gameInfo = parseBetsOpenMessage(message);
                
                if (gameInfo) {
                    console.log(`\n🎰 ✅ CONDIÇÕES ATENDIDAS - ENVIANDO APOSTA`);
                    console.log(`   Tentativa: ${sessao.tentativaAtual + 1}/${sessao.tentativasRestantes}`);
                    console.log(`   Mesa: ${signal.roulette_name}`);
                    console.log(`   Números: ${signal.bets.join(', ')}`);
                    console.log(`   Valor: ${sessao.valorAtual}`);
                    
                    sendBets(ws, gameInfo, signal, sessao.valorAtual);
                    apostaEnviada = true;
                    
                    console.log(`\n   ✅ Aposta enviada!`);
                    console.log(`   apostaEnviada agora: ${apostaEnviada}`);
                    console.log('👁️ Aguardando resultado via Redis Streams...\n');
                } else {
                    console.log('⚠️ gameInfo não encontrado na mensagem');
                }
            } else {
                if (message.includes('<betsopen') || message.includes('<betsclosingsoon')) {
                    console.log('\n❌ [WS MESSAGE] NÃO APOSTOU - Verificando condições:');
                    console.log(`   !apostaEnviada: ${!apostaEnviada} ${!apostaEnviada ? '✅' : '❌'}`);
                    console.log(`   podeTentar(): ${sessao.podeTentar()} ${sessao.podeTentar() ? '✅' : '❌'}`);
                    
                    if (!sessao.podeTentar()) {
                        console.log(`\n   🔍 Detalhamento podeTentar():`);
                        console.log(`      ganhou: ${sessao.ganhou}`);
                        console.log(`      sessaoFinalizada: ${sessao.sessaoFinalizada}`);
                        console.log(`      tentativaAtual < tentativasRestantes: ${sessao.tentativaAtual} < ${sessao.tentativasRestantes} = ${sessao.tentativaAtual < sessao.tentativasRestantes}`);
                    }
                }
            }
        });
        
        ws.on('close', () => {
            const totalTime = ((Date.now() - startTime) / 1000).toFixed(2);
            console.log(`\n🔌 Sessão finalizada em ${totalTime}s`);
            unregisterSignal(signalId);
            console.log('═'.repeat(50) + '\n');
        });
        
        ws.on('error', (error) => {
            console.error('❌ Erro na conexão:', error.message);
            unregisterSignal(signalId);
        });
        
    } catch (error) {
        console.error('❌ Erro durante a execução:', error.message);
        if (ws) ws.close();
        unregisterSignal(signalId);
    }
}

// ============================
// VALIDAÇÃO DE SINAL
// ============================
function validarSinal(signal) {
    if (CONFIG.apenasFirstEntry) {
        const passedSpins = signal.passed_spins || 0;
        if (passedSpins < CONFIG.minPassedSpins) {
            return false;
        }
    }
    
    if (!canProcessSignal(signal)) {
        return false;
    }
    
    return true;
}

// ============================
// CONSUMER GROUPS
// ============================
async function initializeConsumerGroups() {
    try {
        await redis.xgroup('CREATE', 'streams:signals:new', CONFIG.consumerGroup, '0', 'MKSTREAM');
        console.log('✅ Consumer group criado para sinais novos');
    } catch (err) {
        if (err.message.includes('BUSYGROUP')) {
            console.log('ℹ️ Consumer group já existe (sinais novos)');
        } else {
            console.error('❌ Erro:', err.message);
        }
    }
    
    try {
        await redis.xgroup('CREATE', 'streams:signals:updates', CONFIG.consumerGroup, '0', 'MKSTREAM');
        console.log('✅ Consumer group criado para updates');
    } catch (err) {
        if (err.message.includes('BUSYGROUP')) {
            console.log('ℹ️ Consumer group já existe (updates)');
        } else {
            console.error('❌ Erro:', err.message);
        }
    }
}

// ============================
// BUSCAR SINAIS ATIVOS
// ============================
async function loadActiveSignals() {
    console.log('\n🔍 Buscando sinais ativos...');
    
    try {
        const activeSignalsData = await redis.hgetall('signals:active');
        const signals = [];
        
        for (const [signalId, data] of Object.entries(activeSignalsData)) {
            try {
                const signal = JSON.parse(data);
                signals.push(signal);
            } catch (err) {
                console.error(`❌ Erro ao parsear sinal ${signalId}`);
            }
        }
        
        console.log(`📊 Encontrados ${signals.length} sinais ativos no Redis`);
        console.log(`📊 Limite configurado: ${CONFIG.maxSimultaneousSignals} sinais simultâneos`);
        
        if (signals.length === 0) {
            console.log('✔ Nenhum sinal ativo para processar\n');
            return;
        }
        
        // Ordenar por tentativas restantes (menos tentativas = mais urgente)
        signals.sort((a, b) => {
            const tentativasA = (a.gales || 0) - (a.passed_spins || 0);
            const tentativasB = (b.gales || 0) - (b.passed_spins || 0);
            return tentativasA - tentativasB;
        });
        
        let processedCount = 0;
        for (const signal of signals) {
            if (processedCount >= CONFIG.maxSimultaneousSignals) {
                console.log(`⚠️ Limite atingido, ${signals.length - processedCount} sinais em espera`);
                console.log(`💡 Aumente maxSimultaneousSignals para processar mais sinais\n`);
                break;
            }
            
            if (validarSinal(signal)) {
                const tentativasRestantes = (signal.gales || 0) - (signal.passed_spins || 0);
                console.log(`\n🎯 Processando sinal ${processedCount + 1}/${signals.length}:`);
                console.log(`   ID: ${signal.id}`);
                console.log(`   Mesa: ${signal.roulette_name}`);
                console.log(`   Tentativas restantes: ${tentativasRestantes}`);
                
                fazerApostaComGales(signal).catch(err => {
                    console.error(`❌ Erro ao processar sinal ${signal.id}:`, err.message);
                    unregisterSignal(signal.id);
                });
                
                processedCount++;

                await new Promise(resolve => setTimeout(resolve, 500));
            } else {
                console.log(`⏭️ Sinal ${signal.id} ignorado (não passou validação)`);
            }
        }
        
        console.log(`\n✔ ${processedCount} sinais em processamento ativo\n`);
        
    } catch (err) {
        console.error('❌ Erro ao carregar sinais ativos:', err);
    }
}

// ============================
// CONSUMIR STREAMS
// ============================
async function consumeNewSignals() {
    console.log('📡 Iniciando consumo de sinais novos...\n');
    
    while (true) {
        try {
            const results = await redis.xreadgroup(
                'GROUP', CONFIG.consumerGroup, CONFIG.consumerName,
                'BLOCK', 5000,
                'COUNT', 1,
                'STREAMS', 'streams:signals:new', '>'
            );
            
            if (!results) continue;
            
            for (const [stream, messages] of results) {
                for (const [messageId, fields] of messages) {
                    try {
                        const fieldObj = {};
                        for (let i = 0; i < fields.length; i += 2) {
                            fieldObj[fields[i]] = fields[i + 1];
                        }
                        
                        if (!fieldObj.data) {
                            console.error('❌ Campo "data" não encontrado');
                            await redis.xack('streams:signals:new', CONFIG.consumerGroup, messageId);
                            continue;
                        }
                        
                        const signalData = JSON.parse(fieldObj.data);
                        
                        console.log(`\n📨 [NOVO SINAL] Recebido:`);
                        console.log(`   ID: ${signalData.id}`);
                        console.log(`   Mesa: ${signalData.roulette_name}`);
                        console.log(`   Pattern: ${signalData.pattern}`);
                        console.log(`   Gales: ${signalData.gales}`);
                        
                        if (validarSinal(signalData)) {
                            console.log(`   ✅ Sinal válido, processando...`);
                            fazerApostaComGales(signalData).catch(err => {
                                console.error(`❌ Erro ao processar sinal ${signalData.id}:`, err.message);
                                unregisterSignal(signalData.id);
                            });
                        } else {
                            console.log(`   ⏭️ Sinal ignorado (não passou validação)`);
                        }
                        
                        await redis.xack('streams:signals:new', CONFIG.consumerGroup, messageId);
                        
                    } catch (parseErr) {
                        console.error('❌ Erro ao parsear mensagem:', parseErr.message);
                        await redis.xack('streams:signals:new', CONFIG.consumerGroup, messageId);
                    }
                }
            }
        } catch (err) {
            console.error('❌ Erro no loop de consumo:', err.message);
            await new Promise(resolve => setTimeout(resolve, 5000));
        }
    }
}

// ============================
// MAIN
// ============================
async function main() {
    console.log('🤖 BOT DE APOSTAS COM REDIS STREAMS');
    console.log('═'.repeat(50));
    console.log(`Consumer: ${CONFIG.consumerName}`);
    console.log(`Limite: ${CONFIG.maxSimultaneousSignals} sinais simultâneos`);
    console.log(`Martingale: ${CONFIG.usarMartingale ? 'ATIVADO' : 'DESATIVADO'}`);
    console.log(`Valor Base: ${CONFIG.valorBase} centavos`);
    console.log('═'.repeat(50));
    
    try {
        console.log('\n[1/4] Inicializando consumer groups...');
        await initializeConsumerGroups();
        
        console.log('[2/4] Carregando sinais ativos...');
        await loadActiveSignals();
        
        console.log('[3/4] Iniciando consumidores...');
        await Promise.all([
            startUpdatesConsumer(),
            consumeNewSignals()
        ]);
        
    } catch (err) {
        console.error('❌ Erro fatal:', err);
        setTimeout(main, 5000);
    }
}

if (require.main === module) {
    main();
}
import puppeteer from "puppeteer";

async function getWebSocketUrlWithPuppeteer(gameLink:any) {
    const browser = await puppeteer.launch({ 
        headless: true,
        args: ['--no-sandbox', '--disable-setuid-sandbox']
    });
    
    try {
        const page = await browser.newPage();
        await page.setUserAgent('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36');
        
        const webSocketUrls: string[] = [];
        
        await page.evaluateOnNewDocument(() => {
            const pageGlobal = globalThis as any;
            const originalWebSocket = pageGlobal.WebSocket;
            pageGlobal.WebSocket = new Proxy(originalWebSocket, {
                construct(target, args) {
                    const url = args[0];
                    console.log('WS_INTERCEPTED:', url);
                    pageGlobal.__wsUrls = pageGlobal.__wsUrls || [];
                    pageGlobal.__wsUrls.push(url);
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
        
        page.on('websocket', (ws) => {
            const websocketCandidate = ws as { url?: () => string };
            if (typeof websocketCandidate.url === 'function') {
                webSocketUrls.push(websocketCandidate.url());
            }
        });
        
        await page.goto(gameLink, { waitUntil: 'networkidle2', timeout: 60000 });
        await new Promise(resolve => setTimeout(resolve, 3000));
        
        const capturedUrls = await page.evaluate(() => {
            const pageGlobal = globalThis as any;
            return Array.isArray(pageGlobal.__wsUrls) ? pageGlobal.__wsUrls : [];
        }) as string[];
        const allUrls = [...new Set([...capturedUrls, ...webSocketUrls])] as string[];
        
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

export {
    getWebSocketUrlWithPuppeteer
}

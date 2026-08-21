/**
 * Roulette Racetrack Plugin
 * Um plugin JavaScript para criar um racetrack de roleta europeia interativo e responsivo
 * 
 * Uso:
 *   const racetrack = new RouletteRacetrack('#container', options);
 * 
 * Opções:
 *   - width: largura máxima do SVG (padrão: 750)
 *   - height: altura máxima do SVG (padrão: 280)
 *   - responsive: se true, adapta ao container (padrão: true)
 *   - onNumberHover: callback quando passa mouse no número
 *   - onNumberClick: callback quando clica no número
 *   - onSectionClick: callback quando clica na seção
 */

class RouletteRacetrack {
    constructor(selector, options = {}) {
        this.container = typeof selector === 'string'
            ? document.querySelector(selector)
            : selector;

        if (!this.container) {
            throw new Error('Container não encontrado');
        }

        // Opções padrão
        this.options = {
            width: 750,
            height: 280,
            responsive: true,
            onNumberHover: null,
            onNumberClick: null,
            onSectionClick: null,
            ...options
        };

        // Dados da roleta europeia
        this.wheel = [0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36, 11, 30, 8, 23, 10, 5, 24, 16, 33, 1, 20, 14, 31, 9, 22, 18, 29, 7, 28, 12, 35, 3, 26];
        this.reds = [1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36];

        this.sections = {
            'jeu-zero': [12, 35, 3, 26, 0, 32, 15],
            'voisins': [22, 18, 29, 7, 28, 12, 35, 3, 26, 0, 32, 15, 19, 4, 21, 2, 25],
            'orphelins': [17, 34, 6, 1, 20, 14, 31, 9],
            'tiers': [27, 13, 36, 11, 30, 8, 23, 10, 5, 24, 16, 33]
        };

        this.sectionLabels = {
            'jeu-zero': 'Jeu Zero',
            'voisins': 'Voisins du Zéro',
            'orphelins': 'Orphelins',
            'tiers': 'Tiers du Cylindre'
        };

        // Centro de cada célula (preenchido ao construir) — usado pelo setBets
        // para posicionar a ficha com a quantidade apostada sobre o número.
        this.cellCenters = {};

        this.init();
    }

    init() {
        this.injectStyles();
        this.createSVG();
        this.buildRacetrack();
        this.attachEvents();
        
        if (this.options.responsive) {
            this.setupResponsive();
        }
    }

    injectStyles() {
        if (document.getElementById('roulette-racetrack-styles')) return;

        const styles = document.createElement('style');
        styles.id = 'roulette-racetrack-styles';
        styles.textContent = `
            .roulette-racetrack-wrapper {
                width: 100%;
                max-width: 100%;
                display: flex;
                justify-content: center;
            }
            .roulette-racetrack {
                width: 100%;
                height: auto;
                max-width: 750px;
            }
            .roulette-racetrack .number-cell {
                cursor: pointer;
                transition: filter 0.1s ease;
            }
            .roulette-racetrack .number-cell:hover path,
            .roulette-racetrack .number-cell:hover rect {
                filter: brightness(1.4);
            }
            .roulette-racetrack .number-cell.highlighted path,
            .roulette-racetrack .number-cell.highlighted rect {
                stroke: var(--rt-highlight, #00ffff) !important;
                stroke-width: 3px !important;
            }
            .roulette-racetrack .section-btn {
                cursor: pointer;
            }
            .roulette-racetrack .section-btn:hover .section-text {
                fill: var(--rt-highlight, #00ffff);
            }
            .roulette-racetrack .section-btn.active .section-text {
                fill: var(--rt-highlight, #00ffff);
            }
            .roulette-racetrack .section-area {
                transition: fill 0.1s ease;
            }
            .roulette-racetrack .section-btn:hover .section-area {
                fill: rgba(255, 255, 255, 0.10);
            }
            .roulette-racetrack .section-btn.active .section-area {
                fill: rgba(255, 209, 90, 0.14);
            }
            
            /* Responsivo para telas menores */
            @media (max-width: 768px) {
                .roulette-racetrack .section-text {
                    font-size: 12px !important;
                }
                .roulette-racetrack .number-text {
                    font-size: 11px !important;
                }
            }
            
            @media (max-width: 480px) {
                .roulette-racetrack .section-text {
                    font-size: 10px !important;
                }
                .roulette-racetrack .number-text {
                    font-size: 9px !important;
                }
            }
        `;
        document.head.appendChild(styles);
    }

    createSVG() {
        // Wrapper para responsividade
        this.wrapper = document.createElement('div');
        this.wrapper.className = 'roulette-racetrack-wrapper';
        
        const svg = this.createEl('svg', {
            viewBox: `0 0 ${this.options.width} ${this.options.height}`,
            preserveAspectRatio: 'xMidYMid meet',
            class: 'roulette-racetrack'
        });

        // Defs para gradientes
        const defs = this.createEl('defs');

        defs.innerHTML = `
            <linearGradient id="rt-red" x1="0%" y1="0%" x2="0%" y2="100%">
                <stop offset="0%" stop-color="#c3261d"/>
                <stop offset="100%" stop-color="#a91510"/>
            </linearGradient>
            <linearGradient id="rt-black" x1="0%" y1="0%" x2="0%" y2="100%">
                <stop offset="0%" stop-color="#171714"/>
                <stop offset="100%" stop-color="#080907"/>
            </linearGradient>
            <linearGradient id="rt-green" x1="0%" y1="0%" x2="0%" y2="100%">
                <stop offset="0%" stop-color="#329042"/>
                <stop offset="100%" stop-color="#227432"/>
            </linearGradient>
            <linearGradient id="rt-inner" x1="0%" y1="0%" x2="0%" y2="100%">
                <stop offset="0%" stop-color="#181a18"/>
                <stop offset="100%" stop-color="#0e100e"/>
            </linearGradient>
        `;
        svg.appendChild(defs);

        // Inner oval (área preta interna onde ficam os textos)
        svg.appendChild(this.createEl('rect', {
            x: 40, y: 88, width: 604, height: 104, rx: 52, ry: 52, fill: 'url(#rt-inner)'
        }));

        // Grupo de seções
        this.sectionsGroup = this.createEl('g', { id: 'rt-sections' });
        svg.appendChild(this.sectionsGroup);

        // Grupo de números
        this.numbersGroup = this.createEl('g', { id: 'rt-numbers' });
        svg.appendChild(this.numbersGroup);

        // Grupo de fichas apostadas (desenhadas por cima dos números)
        this.chipsGroup = this.createEl('g', { id: 'rt-chips', 'pointer-events': 'none' });
        svg.appendChild(this.chipsGroup);
        this.resultGroup = this.createEl('g', { class: 'rt-result-marker', 'pointer-events': 'none' });
        svg.appendChild(this.resultGroup);

        this.svg = svg;
        this.wrapper.appendChild(svg);
        this.container.appendChild(this.wrapper);
    }

    setupResponsive() {
        // Observar mudanças no tamanho do container
        if (window.ResizeObserver) {
            this.resizeObserver = new ResizeObserver(() => {
                this.handleResize();
            });
            this.resizeObserver.observe(this.container);
        } else {
            // Fallback para navegadores antigos
            window.addEventListener('resize', this.handleResize.bind(this));
        }
        
        // Ajuste inicial
        this.handleResize();
    }

    handleResize() {
        const containerWidth = this.container.clientWidth;
        const maxWidth = this.options.width;
        
        // O SVG já é responsivo via CSS, mas podemos ajustar estilos se necessário
        if (containerWidth < 400) {
            this.svg.classList.add('racetrack-small');
        } else {
            this.svg.classList.remove('racetrack-small');
        }
    }

    createEl(tag, attrs = {}) {
        const el = document.createElementNS('http://www.w3.org/2000/svg', tag);
        for (const [k, v] of Object.entries(attrs)) {
            el.setAttribute(k, v);
        }
        return el;
    }

    getColor(n) {
        if (n === 0) return 'url(#rt-green)';
        return this.reds.includes(n) ? 'url(#rt-red)' : 'url(#rt-black)';
    }

    getColorName(n) {
        if (n === 0) return 'green';
        return this.reds.includes(n) ? 'red' : 'black';
    }

    getNeighbors(n, count = 2) {
        const idx = this.wheel.indexOf(n);
        const neighbors = [];
        for (let i = -count; i <= count; i++) {
            neighbors.push(this.wheel[(idx + i + this.wheel.length) % this.wheel.length]);
        }
        return neighbors;
    }

    buildRacetrack() {
        this.buildSections();
        this.buildNumbers();
    }

    buildSections() {
        // Áreas dentro do oval interno (x 40..644, y 88..192, pontas r=52),
        // com as fronteiras ALINHADAS aos números que cada seção representa
        // (células retas de 38px a partir de x=90):
        // - Jeu Zero {12,35,3,26,0,32,15}: curva esquerda + 15(topo)/12(base)
        //   → bolha curva até x=128 (fim das células 15/12).
        // - Voisins termina em 25(topo, x=318) e 22(base, x=318) → divisória
        //   vertical em x=318 (fronteiras 25|17 e 22|9).
        // - Orphelins termina em 6(topo, x=432) e 1(base, x=508) → divisória
        //   inclinada de (432,88) a (508,192) (fronteiras 6|27 e 1|33).
        // - Tiers: da divisória até a curva direita.
        const sectionsData = [
            {
                key: 'jeu-zero', x: 100, label: 'Jeu Zero',
                d: 'M 92 88 A 52 52 0 0 0 92 192 L 128 192 Q 172 140 128 88 Z'
            },
            {
                key: 'voisins', x: 235, label: 'Voisins',
                d: 'M 128 88 Q 172 140 128 192 L 318 192 L 318 88 Z'
            },
            {
                key: 'orphelins', x: 390, label: 'Orphelins',
                d: 'M 318 88 L 318 192 L 508 192 L 432 88 Z'
            },
            {
                key: 'tiers', x: 550, label: 'Tiers',
                d: 'M 432 88 L 508 192 L 592 192 A 52 52 0 0 0 592 88 Z'
            }
        ];

        sectionsData.forEach(({ key, x, label, d }) => {
            const g = this.createEl('g', { class: 'section-btn', 'data-section': key });

            // Área clicável da seção (o stroke desenha as linhas divisórias).
            g.appendChild(this.createEl('path', {
                class: 'section-area',
                d: d,
                fill: 'rgba(255, 255, 255, 0.02)',
                stroke: 'rgba(255, 255, 255, 0.38)',
                'stroke-width': 1
            }));

            const text = this.createEl('text', {
                class: 'section-text',
                x: x,
                y: 147,
                'text-anchor': 'middle',
                fill: '#ffffff',
                'font-size': 18,
                'font-weight': 800,
                'pointer-events': 'none'
            });
            text.textContent = label;
            g.appendChild(text);

            this.sectionsGroup.appendChild(g);
        });
    }

    buildNumbers() {
        const cellW = 38, cellH = 36;
        const centerY = 140;
        const outerRadius = 88;
        const innerRadius = outerRadius - cellW;
        const topY = centerY - outerRadius;
        const botY = centerY + outerRadius - cellH;
        const straightStartX = 90;

        // Linha superior
        const topNums = [15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36, 11];
        topNums.forEach((n, i) => {
            this.numbersGroup.appendChild(this.createRectCell(n, straightStartX + i * cellW, topY, cellW, cellH));
        });

        // Linha inferior
        const botNums = [12, 28, 7, 29, 18, 22, 9, 31, 14, 20, 1, 33, 16];
        botNums.forEach((n, i) => {
            this.numbersGroup.appendChild(this.createRectCell(n, straightStartX + i * cellW, botY, cellW, cellH));
        });

        const straightEndX = straightStartX + topNums.length * cellW;

        // Curva esquerda
        const leftNums = [32, 0, 26, 3, 35];
        this.buildCurve(leftNums, straightStartX, centerY, outerRadius, innerRadius, 'left');

        // Curva direita
        const rightNums = [30, 8, 23, 10, 5, 24];
        this.buildCurve(rightNums, straightEndX, centerY, outerRadius, innerRadius, 'right');
    }

    createRectCell(n, x, y, w, h) {
        this.cellCenters[n] = { x: x + w / 2, y: y + h / 2 };
        const g = this.createEl('g', { class: 'number-cell', 'data-n': n });
        g.appendChild(this.createEl('rect', {
            x, y, width: w, height: h, fill: this.getColor(n), stroke: '#444', 'stroke-width': 1
        }));
        const text = this.createEl('text', {
            class: 'number-text',
            x: x + w / 2, y: y + h / 2 + 5, 'text-anchor': 'middle',
            fill: '#fff', 'font-size': 19, 'font-weight': 'bold', 'pointer-events': 'none'
        });
        text.textContent = n;
        g.appendChild(text);
        return g;
    }

    buildCurve(nums, centerX, centerY, outerR, innerR, side) {
        const numCells = nums.length;

        nums.forEach((n, i) => {
            const startAngleDeg = 90 - (i * 180 / numCells);
            const endAngleDeg = 90 - ((i + 1) * 180 / numCells);
            const startAngle = startAngleDeg * Math.PI / 180;
            const endAngle = endAngleDeg * Math.PI / 180;

            const sign = side === 'left' ? -1 : 1;
            const sweepOuter = side === 'left' ? 0 : 1;
            const sweepInner = side === 'left' ? 1 : 0;

            const x1Outer = centerX + sign * outerR * Math.cos(startAngle);
            const y1Outer = centerY - outerR * Math.sin(startAngle);
            const x2Outer = centerX + sign * outerR * Math.cos(endAngle);
            const y2Outer = centerY - outerR * Math.sin(endAngle);
            const x1Inner = centerX + sign * innerR * Math.cos(startAngle);
            const y1Inner = centerY - innerR * Math.sin(startAngle);
            const x2Inner = centerX + sign * innerR * Math.cos(endAngle);
            const y2Inner = centerY - innerR * Math.sin(endAngle);

            const pathD = `M ${x1Outer} ${y1Outer} 
                           A ${outerR} ${outerR} 0 0 ${sweepOuter} ${x2Outer} ${y2Outer} 
                           L ${x2Inner} ${y2Inner} 
                           A ${innerR} ${innerR} 0 0 ${sweepInner} ${x1Inner} ${y1Inner} Z`;

            const midAngle = (startAngle + endAngle) / 2;
            const textR = (innerR + outerR) / 2;
            const textX = centerX + sign * textR * Math.cos(midAngle);
            const textY = centerY - textR * Math.sin(midAngle) + 4;

            this.numbersGroup.appendChild(this.createArcCell(n, pathD, textX, textY));
        });
    }

    createArcCell(n, pathD, textX, textY) {
        this.cellCenters[n] = { x: textX, y: textY - 4 };
        const g = this.createEl('g', { class: 'number-cell', 'data-n': n });
        g.appendChild(this.createEl('path', {
            d: pathD, fill: this.getColor(n), stroke: '#444', 'stroke-width': 1
        }));
        const text = this.createEl('text', {
            class: 'number-text',
            x: textX, y: textY, 'text-anchor': 'middle',
            fill: '#fff', 'font-size': 19, 'font-weight': 'bold', 'pointer-events': 'none'
        });
        text.textContent = n;
        g.appendChild(text);
        return g;
    }

    attachEvents() {
        // Eventos dos números
        this.numbersGroup.querySelectorAll('.number-cell').forEach(cell => {
            const n = parseInt(cell.getAttribute('data-n'));

            cell.addEventListener('mouseenter', () => {
                if (this.options.onNumberHover) {
                    this.options.onNumberHover({
                        number: n,
                        color: this.getColorName(n),
                        neighbors: this.getNeighbors(n),
                        sections: this.getNumberSections(n)
                    });
                }
            });

            cell.addEventListener('click', () => {
                this.highlightNumbers([n]);
                if (this.options.onNumberClick) {
                    this.options.onNumberClick({
                        number: n,
                        color: this.getColorName(n),
                        neighbors: this.getNeighbors(n),
                        sections: this.getNumberSections(n)
                    });
                }
            });
        });

        // Eventos das seções
        this.sectionsGroup.querySelectorAll('.section-btn').forEach(btn => {
            const sectionKey = btn.getAttribute('data-section');

            btn.addEventListener('click', () => {
                const nums = this.sections[sectionKey];
                this.highlightSection(sectionKey);
                if (this.options.onSectionClick) {
                    this.options.onSectionClick({
                        key: sectionKey,
                        name: this.sectionLabels[sectionKey],
                        numbers: nums
                    });
                }
            });
        });
    }

    getNumberSections(n) {
        return Object.entries(this.sections)
            .filter(([_, nums]) => nums.includes(n))
            .map(([key]) => this.sectionLabels[key]);
    }

    // Métodos públicos

    highlightNumbers(numbers) {
        this.clearHighlights();
        numbers.forEach(n => {
            this.svg.querySelectorAll(`.number-cell[data-n="${n}"]`).forEach(el => {
                el.classList.add('highlighted');
            });
        });
    }

    highlightSection(sectionKey) {
        this.clearHighlights();
        const nums = this.sections[sectionKey];
        if (nums) {
            this.highlightNumbers(nums);
            this.svg.querySelector(`.section-btn[data-section="${sectionKey}"]`)?.classList.add('active');
        }
    }

    clearHighlights() {
        this.svg.querySelectorAll('.highlighted').forEach(el => el.classList.remove('highlighted'));
        this.svg.querySelectorAll('.active').forEach(el => el.classList.remove('active'));
    }

    /**
     * Mostra o VALOR apostado sobre cada número (ficha dourada).
     * bets: { numero: valor } — valor 0/ausente remove a ficha.
     * Cliques repetidos somam no chamador; aqui só exibimos o acumulado.
     */
    setBets(bets = {}) {
        while (this.chipsGroup.firstChild) {
            this.chipsGroup.removeChild(this.chipsGroup.firstChild);
        }
        Object.entries(bets || {}).forEach(([n, value]) => {
            const c = this.cellCenters[n];
            const amt = Number(value);
            if (!c || !amt) return;

            const label = String(amt).replace('.', ',');
            const r = label.length > 3 ? 13 : 11;
            const fontSize = label.length > 3 ? 9 : 10;

            const g = this.createEl('g', { class: 'bet-chip' });
            g.appendChild(this.createEl('circle', {
                cx: c.x, cy: c.y, r: r,
                fill: '#e7b53c',
                stroke: '#fff8e1',
                'stroke-width': 2,
                'stroke-dasharray': '3 2'
            }));
            const t = this.createEl('text', {
                x: c.x, y: c.y + 3.5,
                'text-anchor': 'middle',
                fill: '#3a2400',
                'font-size': fontSize,
                'font-weight': 'bold'
            });
            t.textContent = label;
            g.appendChild(t);
            this.chipsGroup.appendChild(g);
        });
    }

    clearBets() {
        this.setBets({});
    }

    setResult(number) {
        this.clearResult();
        const c = this.cellCenters[number];
        if (!c || !this.resultGroup) return;
        const glow = this.createEl('circle', {
            cx: c.x, cy: c.y, r: 21,
            fill: 'rgba(0,0,0,0.08)',
            stroke: '#ffb700',
            'stroke-width': 5
        });
        glow.setAttribute('style', 'filter: drop-shadow(0 0 5px rgba(255,183,0,.95))');
        this.resultGroup.appendChild(glow);
    }

    clearResult() {
        if (!this.resultGroup) return;
        while (this.resultGroup.firstChild) this.resultGroup.removeChild(this.resultGroup.firstChild);
    }

    applyHeatmap(heatmap = {}) {
        const map = heatmap || {};
        this.svg.querySelectorAll('.number-cell').forEach((cell) => {
            const n = parseInt(cell.getAttribute('data-n'), 10);
            const intensity = Math.max(0, Math.min(1, Number(map[n] || 0)));
            const shapes = cell.querySelectorAll('path, rect');
            if (intensity <= 0) {
                cell.style.removeProperty('filter');
                cell.style.removeProperty('opacity');
                shapes.forEach((shape) => {
                    shape.style.removeProperty('filter');
                    shape.style.removeProperty('stroke');
                    shape.style.removeProperty('stroke-width');
                });
                return;
            }
            const blur = 7 + (intensity * 14);
            const alpha = 0.28 + (intensity * 0.62);
            const strokeAlpha = 0.35 + (intensity * 0.65);
            cell.style.filter = `drop-shadow(0 0 ${blur}px rgba(255, 120, 30, ${alpha}))`;
            cell.style.opacity = `${0.8 + intensity * 0.2}`;
            shapes.forEach((shape) => {
                shape.style.filter = `brightness(${1.05 + intensity * 0.45}) saturate(${1.05 + intensity * 0.55})`;
                shape.style.stroke = `rgba(255, 160, 70, ${strokeAlpha})`;
                shape.style.strokeWidth = `${1.4 + (intensity * 2.8)}`;
            });
        });
    }

    clearHeatmap() {
        this.svg.querySelectorAll('.number-cell').forEach((cell) => {
            cell.style.removeProperty('filter');
            cell.style.removeProperty('opacity');
            cell.querySelectorAll('path, rect').forEach((shape) => {
                shape.style.removeProperty('filter');
                shape.style.removeProperty('stroke');
                shape.style.removeProperty('stroke-width');
            });
        });
    }

    getWheelSequence() {
        return [...this.wheel];
    }

    getSections() {
        return { ...this.sections };
    }

    destroy() {
        if (this.resizeObserver) {
            this.resizeObserver.disconnect();
        }
        this.container.removeChild(this.wrapper);
    }
}

/**
 * Pano de apostas (betting table) em SVG — mesmo estilo visual do racetrack
 * (gradientes rt-red/rt-black/rt-green, fichas via setBets). É um objeto irmão
 * do plugin: compartilha a convenção de cores e a API setBets/clearBets.
 *
 * Uso:
 *   const felt = new RouletteBetTable('#container', { onNumberClick });
 *   felt.setBets({ 0: 0.5, 17: 1 });
 */
class RouletteBetTable {
    constructor(selector, options = {}) {
        this.container = typeof selector === 'string'
            ? document.querySelector(selector) : selector;
        if (!this.container) throw new Error('Container não encontrado');

        this.options = { width: 648, height: 220, onNumberClick: null, onSectionClick: null, ...options };
        this.reds = [1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36];
        this.cellCenters = {};

        // reaproveita utilitários do racetrack
        this.createEl = RouletteRacetrack.prototype.createEl;
        this.getColor = RouletteRacetrack.prototype.getColor;
        this.getColorName = RouletteRacetrack.prototype.getColorName;
        this.setBets = RouletteRacetrack.prototype.setBets;
        this.clearBets = RouletteRacetrack.prototype.clearBets;
        this.setResult = RouletteRacetrack.prototype.setResult;
        this.clearResult = RouletteRacetrack.prototype.clearResult;

        this._build();
    }

    _build() {
        RouletteRacetrack.prototype.injectStyles();

        this.wrapper = document.createElement('div');
        this.wrapper.className = 'roulette-racetrack-wrapper';

        const svg = this.createEl('svg', {
            viewBox: `0 0 ${this.options.width} ${this.options.height}`,
            preserveAspectRatio: 'xMidYMid meet',
            class: 'roulette-racetrack roulette-bettable'
        });

        const defs = this.createEl('defs');
        defs.innerHTML = `
            <linearGradient id="rt-red" x1="0%" y1="0%" x2="0%" y2="100%"><stop offset="0%" stop-color="#c3261d"/><stop offset="100%" stop-color="#a91510"/></linearGradient>
            <linearGradient id="rt-black" x1="0%" y1="0%" x2="0%" y2="100%"><stop offset="0%" stop-color="#171714"/><stop offset="100%" stop-color="#080907"/></linearGradient>
            <linearGradient id="rt-green" x1="0%" y1="0%" x2="0%" y2="100%"><stop offset="0%" stop-color="#329042"/><stop offset="100%" stop-color="#227432"/></linearGradient>
        `;
        svg.appendChild(defs);

        this.numbersGroup = this.createEl('g', { id: 'ft-numbers' });
        svg.appendChild(this.numbersGroup);
        this.outsideGroup = this.createEl('g', { id: 'ft-outside' });
        svg.appendChild(this.outsideGroup);
        this.chipsGroup = this.createEl('g', { id: 'rt-chips', 'pointer-events': 'none' });
        svg.appendChild(this.chipsGroup);
        this.resultGroup = this.createEl('g', { class: 'rt-result-marker', 'pointer-events': 'none' });
        svg.appendChild(this.resultGroup);

        this.svg = svg;
        this._buildNumbers();
        this._buildOutside();

        this.wrapper.appendChild(svg);
        this.container.appendChild(this.wrapper);
        this._attach();
    }

    _numCell(n, x, y, w, h) {
        this.cellCenters[n] = { x: x + w / 2, y: y + h / 2 };
        const g = this.createEl('g', { class: 'number-cell', 'data-n': n });
        g.appendChild(this.createEl('rect', {
            x, y, width: w, height: h, rx: 3, ry: 3,
            fill: this.getColor(n), stroke: 'rgba(255,255,255,0.55)', 'stroke-width': 1
        }));
        const t = this.createEl('text', {
            class: 'number-text', x: x + w / 2, y: y + h / 2 + 5,
            'text-anchor': 'middle', fill: '#fff', 'font-size': 15,
            'font-weight': 'bold', 'pointer-events': 'none'
        });
        t.textContent = n;
        g.appendChild(t);
        this.numbersGroup.appendChild(g);
    }

    _outCell(label, x, y, w, h, colorSquare, numbers = []) {
        const g = this.createEl('g', {
            class: 'outside-cell',
            'data-numbers': numbers.join(','),
        });
        g.appendChild(this.createEl('rect', {
            x, y, width: w, height: h, rx: 3, ry: 3,
            fill: 'rgba(10,18,30,0.5)', stroke: 'rgba(255,255,255,0.4)', 'stroke-width': 1
        }));
        if (colorSquare) {
            const s = 14;
            const r = this.createEl('rect', {
                x: x + w / 2 - s / 2, y: y + h / 2 - s / 2, width: s, height: s,
                transform: `rotate(45 ${x + w / 2} ${y + h / 2})`,
                fill: colorSquare === 'red' ? '#d02b35' : '#14171c',
                stroke: 'rgba(255,255,255,0.4)', 'stroke-width': 1
            });
            g.appendChild(r);
        } else {
            const t = this.createEl('text', {
                x: x + w / 2, y: y + h / 2 + 4, 'text-anchor': 'middle',
                fill: '#dfe4ea', 'font-size': 12, 'font-weight': 600
            });
            t.textContent = label;
            g.appendChild(t);
        }
        this.outsideGroup.appendChild(g);
    }

    _buildNumbers() {
        const x0 = 48, y0 = 4, cw = 46, ch = 44;
        // zero (coluna alta à esquerda)
        this.cellCenters[0] = { x: x0 / 2 + 2, y: y0 + ch * 1.5 };
        const gz = this.createEl('g', { class: 'number-cell', 'data-n': 0 });
        gz.appendChild(this.createEl('path', {
            d: `M ${x0} ${y0} H 22 A 22 22 0 0 0 22 ${y0 + ch * 3} H ${x0} Z`,
            fill: this.getColor(0), stroke: 'rgba(255,255,255,0.55)', 'stroke-width': 1
        }));
        const tz = this.createEl('text', {
            class: 'number-text', x: (x0 + 8) / 2, y: y0 + ch * 1.5 + 5,
            'text-anchor': 'middle', fill: '#fff', 'font-size': 16,
            'font-weight': 'bold', 'pointer-events': 'none'
        });
        tz.textContent = 0;
        gz.appendChild(tz);
        this.numbersGroup.appendChild(gz);

        const rows = [
            [3, 6, 9, 12, 15, 18, 21, 24, 27, 30, 33, 36],
            [2, 5, 8, 11, 14, 17, 20, 23, 26, 29, 32, 35],
            [1, 4, 7, 10, 13, 16, 19, 22, 25, 28, 31, 34]
        ];
        rows.forEach((row, ri) => {
            row.forEach((n, ci) => {
                this._numCell(n, x0 + ci * cw, y0 + ri * ch, cw, ch);
            });
        });
        this._gridRight = x0 + 12 * cw; // fim da grade (início do 2:1)
        this._gridBottom = y0 + 3 * ch;
    }

    _buildOutside() {
        const x0 = 48, y0 = 4, cw = 46, ch = 44;
        const right = this._gridRight, bottom = this._gridBottom;
        // coluna 2:1
        const columns = [
            [3, 6, 9, 12, 15, 18, 21, 24, 27, 30, 33, 36],
            [2, 5, 8, 11, 14, 17, 20, 23, 26, 29, 32, 35],
            [1, 4, 7, 10, 13, 16, 19, 22, 25, 28, 31, 34],
        ];
        for (let i = 0; i < 3; i++) this._outCell('2:1', right, y0 + i * ch, 40, ch, null, columns[i]);
        // dúzias
        const dozW = (right - x0) / 3;
        ['1.ª 12', '2.ª 12', '3.ª 12'].forEach((d, i) => {
            this._outCell(d, x0 + i * dozW, bottom + 4, dozW, 34, null,
                Array.from({ length: 12 }, (_, offset) => i * 12 + offset + 1));
        });
        // even money
        const evW = (right - x0) / 6;
        const evy = bottom + 42;
        this._outCell('1-18', x0 + 0 * evW, evy, evW, 34, null, Array.from({ length: 18 }, (_, i) => i + 1));
        this._outCell('PAR', x0 + 1 * evW, evy, evW, 34, null, Array.from({ length: 18 }, (_, i) => (i + 1) * 2));
        this._outCell('', x0 + 2 * evW, evy, evW, 34, 'red', this.reds);
        this._outCell('', x0 + 3 * evW, evy, evW, 34, 'black', Array.from({ length: 36 }, (_, i) => i + 1).filter((n) => !this.reds.includes(n)));
        this._outCell('ÍMPAR', x0 + 4 * evW, evy, evW, 34, null, Array.from({ length: 18 }, (_, i) => i * 2 + 1));
        this._outCell('19-36', x0 + 5 * evW, evy, evW, 34, null, Array.from({ length: 18 }, (_, i) => i + 19));
    }

    _attach() {
        this.numbersGroup.querySelectorAll('.number-cell').forEach((cell) => {
            const n = parseInt(cell.getAttribute('data-n'), 10);
            cell.addEventListener('click', () => {
                if (this.options.onNumberClick) this.options.onNumberClick({ number: n });
            });
        });
        this.outsideGroup.querySelectorAll('.outside-cell').forEach((cell) => {
            cell.addEventListener('click', () => {
                const numbers = (cell.getAttribute('data-numbers') || '')
                    .split(',').map(Number).filter(Number.isFinite);
                if (numbers.length && this.options.onSectionClick) {
                    this.options.onSectionClick({ numbers });
                }
            });
        });
    }

    destroy() {
        if (this.wrapper && this.wrapper.parentNode) this.wrapper.parentNode.removeChild(this.wrapper);
    }
}

// Exportar para uso como módulo ou global
if (typeof module !== 'undefined' && module.exports) {
    module.exports = RouletteRacetrack;
    module.exports.RouletteRacetrack = RouletteRacetrack;
    module.exports.RouletteBetTable = RouletteBetTable;
} else {
    window.RouletteRacetrack = RouletteRacetrack;
    window.RouletteBetTable = RouletteBetTable;
}

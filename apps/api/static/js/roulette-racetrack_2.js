/**
 * Roulette Racetrack Plugin
 * Um plugin JavaScript para criar um racetrack de roleta europeia interativo
 * 
 * Uso:
 *   const racetrack = new RouletteRacetrack('#container', options);
 * 
 * Opções:
 *   - width: largura do SVG (padrão: 750)
 *   - height: altura do SVG (padrão: 280)
 *   - onNumberHover: callback quando passa mouse no número (recebe número)
 *   - onNumberClick: callback quando clica no número (recebe número)
 *   - onSectionClick: callback quando clica na seção (recebe nome e números)
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

        this.init();
    }

    init() {
        this.injectStyles();
        this.createSVG();
        this.buildRacetrack();
        this.attachEvents();
    }

    injectStyles() {
        if (document.getElementById('roulette-racetrack-styles')) return;

        const styles = document.createElement('style');
        styles.id = 'roulette-racetrack-styles';
        styles.textContent = `
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
                stroke: #00ffff !important;
                stroke-width: 3px !important;
            }
            .roulette-racetrack .section-btn {
                cursor: pointer;
            }
            .roulette-racetrack .section-btn:hover .section-text {
                fill: #00ffff;
            }
            .roulette-racetrack .section-btn.active .section-text {
                fill: #00ffff;
            }
        `;
        document.head.appendChild(styles);
    }

    createSVG() {
        const svg = this.createEl('svg', {
            width: this.options.width,
            height: this.options.height,
            viewBox: `0 0 ${this.options.width} ${this.options.height}`,
            class: 'roulette-racetrack'
        });

        // Defs para gradientes
        const defs = this.createEl('defs');

        defs.innerHTML = `
            <linearGradient id="rt-red" x1="0%" y1="0%" x2="0%" y2="100%">
                <stop offset="0%" stop-color="#e63946"/>
                <stop offset="100%" stop-color="#9d0208"/>
            </linearGradient>
            <linearGradient id="rt-black" x1="0%" y1="0%" x2="0%" y2="100%">
                <stop offset="0%" stop-color="#2b2d42"/>
                <stop offset="100%" stop-color="#14213d"/>
            </linearGradient>
            <linearGradient id="rt-green" x1="0%" y1="0%" x2="0%" y2="100%">
                <stop offset="0%" stop-color="#2a9d8f"/>
                <stop offset="100%" stop-color="#1a7f72"/>
            </linearGradient>
            <linearGradient id="rt-inner" x1="0%" y1="0%" x2="0%" y2="100%">
                <stop offset="0%" stop-color="#1a1a2e"/>
                <stop offset="100%" stop-color="#16162a"/>
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

        this.svg = svg;
        this.container.appendChild(svg);
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
        const sectionsData = [
            { key: 'jeu-zero', x: 118, label: 'Jeu Zero' },
            { key: 'voisins', x: 250, label: 'Voisins' },
            { key: 'orphelins', x: 382, label: 'Orphelins' },
            { key: 'tiers', x: 514, label: 'Tiers' }
        ];

        sectionsData.forEach(({ key, x, label }) => {
            const g = this.createEl('g', { class: 'section-btn', 'data-section': key });

            const text = this.createEl('text', {
                class: 'section-text',
                x: x,
                y: 147,
                'text-anchor': 'middle',
                fill: '#cccccc',
                'font-size': 15,
                'font-weight': 600
            });
            text.textContent = label;
            g.appendChild(text);

            this.sectionsGroup.appendChild(g);
        });
    }

    buildNumbers() {
        const cellW = 38, cellH = 36;
        const centerY = 140;
        const outerRadius = 88; // Reduzido 2px
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
        const g = this.createEl('g', { class: 'number-cell', 'data-n': n });
        g.appendChild(this.createEl('rect', {
            x, y, width: w, height: h, fill: this.getColor(n), stroke: '#444', 'stroke-width': 1
        }));
        const text = this.createEl('text', {
            x: x + w / 2, y: y + h / 2 + 5, 'text-anchor': 'middle',
            fill: '#fff', 'font-size': 13, 'font-weight': 'bold', 'pointer-events': 'none'
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
        const g = this.createEl('g', { class: 'number-cell', 'data-n': n });
        g.appendChild(this.createEl('path', {
            d: pathD, fill: this.getColor(n), stroke: '#444', 'stroke-width': 1
        }));
        const text = this.createEl('text', {
            x: textX, y: textY, 'text-anchor': 'middle',
            fill: '#fff', 'font-size': 13, 'font-weight': 'bold', 'pointer-events': 'none'
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

    getWheelSequence() {
        return [...this.wheel];
    }

    getSections() {
        return { ...this.sections };
    }

    destroy() {
        this.container.removeChild(this.svg);
    }
}

// Exportar para uso como módulo ou global
if (typeof module !== 'undefined' && module.exports) {
    module.exports = RouletteRacetrack;
} else {
    window.RouletteRacetrack = RouletteRacetrack;
}


import React, { useState, useEffect, useRef } from "react";
import { base44 } from "@/api/base44Client";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Loader2, Sparkles, TrendingUp, History, Zap, AlertCircle, Target, Calendar, Clock } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { differenceInDays } from "date-fns";
import AnimatedWheel from "@/components/roulette/AnimatedWheel";
import StatsDashboard from "@/components/roulette/StatsDashboard";
import RouletteHistory from "@/components/roulette/RouletteHistory";
import SuggestionCard from "@/components/roulette/SuggestionCard";
import SuggestionHistory from "@/components/roulette/SuggestionHistory";
import apiProtection from "../components/ApiProtection";

// Ofuscação em múltiplas camadas
const _0x4a2b = [
  'YUhSMGNITTZMeTloY0drdWNtVjJaWE5pYjNRdVkyOXRMbUp5TDJocGMzUnZjbmt2Y0hKaFoyMWhkR2xqTFdKeVlYcHBiR2xoYmkxeWIzVnNaWFIwWlE9PQ=='
];
const getApiEndpoint = () => {
  try {
    // Decodificar em camadas
    const layer1 = atob(_0x4a2b[0]);
    const layer2 = atob(layer1);
    return layer2;
  } catch (e) {
    return null;
  }
};

const _k = {
  a: [26, 3, 35, 12, 28, 7, 29, 18, 22],
  b: [32, 15, 19, 4, 21, 2, 25, 17, 34],
  c: [6, 27, 13, 36, 11, 30, 8, 23, 10],
  d: [5, 24, 16, 33, 1, 20, 14, 31, 9]
};

const getSectorData = () => ({
  1: _k.a, 2: _k.b, 3: _k.c, 4: _k.d
});

const _n = {
  0: [32, 15], 32: [15, 19], 15: [19, 4], 19: [4, 21], 4: [21, 2],
  21: [2, 25], 2: [25, 17], 25: [17, 34], 17: [34, 6], 34: [6, 27],
  6: [27, 13], 27: [13, 36], 13: [36, 11], 36: [11, 30], 11: [30, 8],
  30: [8, 23], 8: [23, 10], 23: [10, 5], 10: [5, 24], 5: [24, 16],
  24: [16, 33], 16: [33, 1], 33: [1, 20], 1: [20, 14], 20: [14, 31],
  14: [31, 9], 31: [9, 22], 9: [22, 18], 22: [18, 29], 18: [29, 7],
  29: [7, 28], 7: [28, 12], 28: [12, 35], 12: [35, 3], 35: [3, 26],
  3: [26, 0], 26: [0, 32]
};

const _m = {
  1: 10, 10: 1, 2: 20, 20: 2, 3: 30, 30: 3,
  6: 9, 9: 6, 16: 19, 19: 16, 26: 29, 29: 26,
  13: 31, 31: 13, 12: 21, 21: 12, 32: 23, 23: 32
};

const SECTORS = getSectorData();
const NEIGHBORS = _n;
const MIRRORS = _m;

const getSector = (num) => {
  if (num === 0) return 0;
  for (const [sector, numbers] of Object.entries(SECTORS)) {
    if (numbers.includes(num)) return parseInt(sector);
  }
  return 0;
};

const getDozen = (num) => num === 0 ? 0 : Math.ceil(num / 12);
const getColumn = (num) => num === 0 ? 0 : ((num - 1) % 3) + 1;
const getParity = (num) => num === 0 ? 'zero' : (num % 2 === 0 ? 'par' : 'ímpar');
const getColor = (num) => {
  if (num === 0) return 'verde';
  const reds = [1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36];
  return reds.includes(num) ? 'vermelho' : 'preto';
};
const getTerminal = (num) => num % 10;

// Função para obter vizinhos de 2º nível
const getNeighborsExtended = (num, levels = 2) => {
  const neighbors = new Set();
  
  const addNeighbors = (n, level) => {
    if (level > levels || !NEIGHBORS[n]) return;
    NEIGHBORS[n].forEach(neighbor => {
      neighbors.add(neighbor);
      if (level < levels) {
        addNeighbors(neighbor, level + 1);
      }
    });
  };
  
  addNeighbors(num, 1);
  return Array.from(neighbors);
};

// ============================================
// BLOQUEIOS INTELIGENTES
// ============================================

const checkBlockedNumbers = (history) => {
  console.log("🚫 === VERIFICANDO BLOQUEIOS ===");
  
  const blocked = new Set();
  const recent10 = history.slice(0, 10);
  const recent5 = history.slice(0, 5);
  const recent3 = history.slice(0, 3);
  
  // BLOQUEIO 1: Repetição recente SEM contexto narrativo
  // Se número repetiu nos últimos 3, bloquear EXCETO se houver padrão de tripla
  for (let i = 0; i < Math.min(2, recent3.length - 1); i++) {
    const a = recent3[i];
    const b = recent3[i + 1];
    
    // Se acabou de repetir (16→16), bloquear
    if (a === b) {
      // Verificar se há padrão de tripla (16→16→16)
      const hasTripla = i === 0 && recent3[2] === a;
      
      if (!hasTripla) {
        blocked.add(a);
        console.log(`  ❌ Bloqueado ${a}: repetição recente sem contexto de tripla`);
      } else {
        console.log(`  ✅ ${a} permitido: padrão de tripla detectado`);
      }
    }
  }
  
  // BLOQUEIO 2: Terminal do último número (evitar T5→T5 imediato)
  const lastNum = recent3[0];
  const lastTerminal = getTerminal(lastNum);
  
  // Bloquear outros números com mesmo terminal, exceto o próprio (que já foi bloqueado acima se repetiu)
  for (let n = 1; n <= 36; n++) {
    if (n !== lastNum && getTerminal(n) === lastTerminal) {
      // Verificar se não há padrão de alternância de terminais
      const hasTerminalPattern = recent5.filter(num => getTerminal(num) === lastTerminal).length >= 3;
      
      if (!hasTerminalPattern) {
        blocked.add(n);
        console.log(`  ❌ Bloqueado ${n}: terminal ${lastTerminal} repetido sem padrão`);
      }
    }
  }
  
  // BLOQUEIO 3: Vizinho imediato do último que acabou de sair
  if (recent3.length >= 2) {
    const num1 = recent3[0];
    const num2 = recent3[1];
    
    // Se num2→num1 aconteceu, e num1 é vizinho de num2, bloquear retorno imediato
    if (NEIGHBORS[num2] && NEIGHBORS[num2].includes(num1)) {
      // Bloquear num2 temporariamente (evitar ping-pong)
      blocked.add(num2);
      console.log(`  ❌ Bloqueado ${num2}: ping-pong de vizinhos com ${num1}`);
    }
  }
  
  // BLOQUEIO 4: Espelho imediato recente
  const lastMirror = MIRRORS[lastNum];
  if (lastMirror && recent5.includes(lastMirror)) {
    blocked.add(lastMirror);
    console.log(`  ❌ Bloqueado ${lastMirror}: espelho de ${lastNum} saiu recentemente`);
  }
  
  // BLOQUEIO 5: Números que saíram 2x nos últimos 5
  const freq5 = {};
  recent5.forEach(num => {
    freq5[num] = (freq5[num] || 0) + 1;
  });
  
  Object.entries(freq5).forEach(([numStr, count]) => {
    if (count >= 2) {
      const num = parseInt(numStr);
      // Verificar se não há padrão de tripla ou sequência
      const hasPattern = count >= 3 || (recent3[0] === num && recent3[1] === num);
      
      if (!hasPattern) {
        blocked.add(num);
        console.log(`  ❌ Bloqueado ${num}: apareceu ${count}x nos últimos 5 sem padrão`);
      }
    }
  });
  
  console.log(`✅ Total de números bloqueados: ${blocked.size}`);
  return blocked;
};

// ============================================
// 1. ANÁLISE CHAIN - NARRATIVA SEQUENCIAL
// ============================================

const analyzeChain = (history) => {
  console.log("🔗 === ANÁLISE CHAIN (NARRATIVA) ===");
  
  const longWindow = history.slice(0, 200);
  const shortWindow = history.slice(0, 15);
  const chainData = {
    anchors: {},
    pulls: {},
    missing: new Set(),
    crescentes: [],
    inversions: [],
    patterns: []
  };
  
  // 1. IDENTIFICAR ÂNCORAS (números que aparecem múltiplas vezes)
  const anchorPositions = {};
  longWindow.forEach((num, idx) => {
    if (!anchorPositions[num]) anchorPositions[num] = [];
    anchorPositions[num].push(idx);
  });
  
  // Filtrar âncoras válidas (aparecem ≥2x)
  Object.entries(anchorPositions).forEach(([numStr, positions]) => {
    if (positions.length >= 2) {
      const num = parseInt(numStr);
      chainData.anchors[num] = { positions, pulls: [] };
    }
  });
  
  // 2. IDENTIFICAR PUXADAS (números que aparecem após âncoras repetidamente)
  Object.entries(chainData.anchors).forEach(([anchorStr, anchorInfo]) => {
    const anchor = parseInt(anchorStr);
    const recentOccurrences = anchorInfo.positions.slice(0, 2);
    
    const pullCounts = {};
    recentOccurrences.forEach(anchorIdx => {
      for (let offset = 1; offset <= 5; offset++) {
        const targetIdx = anchorIdx - offset;
        if (targetIdx >= 0 && targetIdx < longWindow.length) {
          const pulledNum = longWindow[targetIdx];
          pullCounts[pulledNum] = (pullCounts[pulledNum] || 0) + 1;
        }
      }
    });
    
    Object.entries(pullCounts).forEach(([pulledStr, count]) => {
      if (count >= 2) {
        const pulled = parseInt(pulledStr);
        chainData.anchors[anchor].pulls.push(pulled);
        if (!chainData.pulls[anchor]) chainData.pulls[anchor] = [];
        chainData.pulls[anchor].push(pulled);
      }
    });
  });
  
  // 3. DETECTAR CRESCENTES/DECRESCENTES
  for (let i = 0; i < Math.min(10, shortWindow.length - 2); i++) {
    const a = shortWindow[i];
    const b = shortWindow[i + 1];
    const c = shortWindow[i + 2];
    
    if (a < b && b < c && (c - b) <= 3 && (b - a) <= 3) {
      const nextNum = c + 1;
      if (nextNum >= 1 && nextNum <= 36) {
        chainData.crescentes.push({ sequence: [a, b, c], missing: nextNum });
      }
    }
    
    if (getTerminal(b) === getTerminal(a) + 1 && getTerminal(c) === getTerminal(b) + 1) {
      const nextTerminal = getTerminal(c) + 1;
      if (nextTerminal <= 9) {
        chainData.crescentes.push({ 
          sequence: [a, b, c], 
          missing: Math.floor(c / 10) * 10 + nextTerminal,
          type: 'terminal'
        });
      }
    }
  }
  
  // 4. DETECTAR INVERSÕES
  const pairs = {};
  for (let i = 0; i < Math.min(30, longWindow.length - 1); i++) {
    const a = longWindow[i];
    const b = longWindow[i + 1];
    const key = `${a}-${b}`;
    const inverseKey = `${b}-${a}`;
    
    if (!pairs[key]) pairs[key] = 0;
    pairs[key]++;
    
    if (pairs[inverseKey] && pairs[inverseKey] > 0) {
      chainData.inversions.push({ original: [a, b], inverse: [b, a] });
    }
  }
  
  // 5. DETECTAR PADRÕES NARRATIVOS
  for (let i = 0; i < Math.min(8, shortWindow.length - 3); i++) {
    const t1 = getTerminal(shortWindow[i]);
    const t2 = getTerminal(shortWindow[i + 1]);
    const t3 = getTerminal(shortWindow[i + 2]);
    
    if (t1 === t3 && t1 !== t2) {
      chainData.patterns.push({
        type: 'terminal_alternation',
        sequence: [shortWindow[i], shortWindow[i + 1], shortWindow[i + 2]],
        expectedTerminal: t2
      });
    }
  }
  
  for (let i = 0; i < Math.min(8, shortWindow.length - 2); i++) {
    const a = shortWindow[i];
    const b = shortWindow[i + 1];
    if (a === b) {
      chainData.patterns.push({
        type: 'repetition_focus',
        number: a,
        context: shortWindow.slice(Math.max(0, i - 2), i + 3)
      });
    }
  }
  
  // 6. CALCULAR FALTANTES NARRATIVOS
  Object.entries(chainData.pulls).forEach(([anchorStr, pulls]) => {
    const anchor = parseInt(anchorStr);
    if (shortWindow.slice(0, 5).includes(anchor)) {
      pulls.forEach(pull => chainData.missing.add(pull));
    }
  });
  
  chainData.crescentes.forEach(crescente => {
    if (crescente.missing && crescente.missing >= 1 && crescente.missing <= 36) {
      chainData.missing.add(crescente.missing);
    }
  });
  
  const recent3 = shortWindow.slice(0, 3);
  chainData.inversions.forEach(inversion => {
    const [a, b] = inversion.original;
    if (recent3.includes(a) && recent3.includes(b)) {
      const aIdx = recent3.indexOf(a);
      const bIdx = recent3.indexOf(b);
      if (aIdx > bIdx) {
        chainData.missing.add(a);
        chainData.missing.add(b);
      }
    }
  });
  
  const expandedMissing = new Set(chainData.missing);
  chainData.missing.forEach(num => {
    if (NEIGHBORS[num]) {
      NEIGHBORS[num].forEach(n => expandedMissing.add(n));
    }
    if (MIRRORS[num]) {
      expandedMissing.add(MIRRORS[num]);
    }
  });
  
  const topChain = Array.from(expandedMissing).filter(n => n !== 0).slice(0, 20);
  
  console.log("✅ Chain:", {
    anchors: Object.keys(chainData.anchors).length,
    pulls: Object.keys(chainData.pulls).length,
    crescentes: chainData.crescentes.length,
    inversions: chainData.inversions.length,
    patterns: chainData.patterns.length,
    missing: topChain.length
  });
  
  return { numbers: topChain, patterns: chainData.patterns };
};

// ============================================
// 2. ANÁLISE DIRETA DO ÚLTIMO NÚMERO
// ============================================

const analyzeDirectNumber = (history) => {
  console.log("🎯 === ANÁLISE DIRETA DO ÚLTIMO NÚMERO ===");
  
  const lastNumber = history[0];
  const directAnalysis = {
    lastNumber,
    immediateNeighbors: [],
    extendedNeighbors: [],
    mirror: null,
    sector: getSector(lastNumber),
    sectorNumbers: [],
    terminalFamily: [],
    oppositeColor: null
  };
  
  if (NEIGHBORS[lastNumber]) {
    directAnalysis.immediateNeighbors = NEIGHBORS[lastNumber];
  }
  
  directAnalysis.extendedNeighbors = getNeighborsExtended(lastNumber, 2);
  
  if (MIRRORS[lastNumber]) {
    directAnalysis.mirror = MIRRORS[lastNumber];
  }
  
  if (directAnalysis.sector !== 0) {
    directAnalysis.sectorNumbers = SECTORS[directAnalysis.sector];
  }
  
  const terminal = getTerminal(lastNumber);
  for (let n = 1; n <= 36; n++) {
    if (getTerminal(n) === terminal) {
      directAnalysis.terminalFamily.push(n);
    }
  }
  
  const currentColor = getColor(lastNumber);
  directAnalysis.oppositeColor = currentColor === 'vermelho' ? 'preto' : 'vermelho';
  
  console.log("✅ Análise direta:", {
    lastNumber,
    immediateNeighbors: directAnalysis.immediateNeighbors,
    mirror: directAnalysis.mirror,
    sector: directAnalysis.sector
  });
  
  return directAnalysis;
};

// ============================================
// 3. ANÁLISE DE PADRÕES RECENTES
// ============================================

const analyzeRecentPatterns = (history) => {
  console.log("🔍 === ANÁLISE DE PADRÕES RECENTES ===");
  
  const recent = history.slice(0, 20);
  const patterns = {
    frequentNumbers: [],
    frequentNeighbors: new Set(),
    sequenceTargets: new Set(),
    sectorTrend: {},
    colorPattern: []
  };
  
  const frequencies = {};
  recent.forEach(num => {
    frequencies[num] = (frequencies[num] || 0) + 1;
  });
  patterns.frequentNumbers = Object.entries(frequencies)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 8)
    .map(([num]) => parseInt(num));
  
  for (let i = 0; i < Math.min(10, recent.length - 1); i++) {
    const num1 = recent[i];
    const num2 = recent[i + 1];
    if (NEIGHBORS[num1] && NEIGHBORS[num1].includes(num2)) {
      patterns.frequentNeighbors.add(num2);
      if (NEIGHBORS[num2]) {
        NEIGHBORS[num2].forEach(n => patterns.frequentNeighbors.add(n));
      }
    }
  }
  
  const sequences = {};
  for (let i = 0; i < Math.min(15, recent.length - 1); i++) {
    const current = recent[i];
    const next = recent[i + 1];
    const key = `${current}->${next}`;
    sequences[key] = (sequences[key] || 0) + 1;
  }
  
  Object.entries(sequences)
    .filter(([key, count]) => count >= 2)
    .forEach(([key]) => {
      const target = parseInt(key.split('->')[1]);
      patterns.sequenceTargets.add(target);
    });
  
  recent.slice(0, 10).forEach(num => {
    const sector = getSector(num);
    if (sector !== 0) {
      patterns.sectorTrend[sector] = (patterns.sectorTrend[sector] || 0) + 1;
    }
  });
  
  patterns.colorPattern = recent.slice(0, 5).map(n => getColor(n));
  
  console.log("✅ Padrões recentes:", {
    frequentNumbers: patterns.frequentNumbers.length,
    frequentNeighbors: patterns.frequentNeighbors.size,
    sequenceTargets: patterns.sequenceTargets.size
  });
  
  return patterns;
};

// ============================================
// 4. ANÁLISE ESTELAR SIMPLIFICADA
// ============================================

const analyzeEstelar = (history) => {
  console.log("⭐ === ANÁLISE ESTELAR ===");
  
  const recent = history.slice(0, 100);
  const estelarSuggestions = new Set();
  
  recent.slice(0, 5).forEach(num => {
    if (MIRRORS[num]) {
      estelarSuggestions.add(MIRRORS[num]);
    }
  });
  
  recent.slice(0, 5).forEach(num => {
    const terminal = getTerminal(num);
    for (let n = 1; n <= 36; n++) {
      if (getTerminal(n) === terminal && n !== num) {
        estelarSuggestions.add(n);
      }
    }
  });
  
  const topEstelar = Array.from(estelarSuggestions).slice(0, 15);
  console.log("✅ Estelar:", { suggestions: topEstelar.length });
  return { numbers: topEstelar };
};

// ============================================
// 5. ANÁLISE MASTER SIMPLIFICADA
// ============================================

const analyzeMaster = (history) => {
  console.log("🎓 === ANÁLISE MASTER ===");
  
  const recent = history.slice(0, 15);
  const masterData = {
    dozen: {},
    column: {},
    suggestions: new Set()
  };
  
  recent.forEach((num) => {
    const dozen = getDozen(num);
    const column = getColumn(num);
    if (dozen !== 0) masterData.dozen[dozen] = (masterData.dozen[dozen] || 0) + 1;
    if (column !== 0) masterData.column[column] = (masterData.column[column] || 0) + 1;
  });
  
  const dominantDozen = parseInt(
    Object.entries(masterData.dozen)
      .sort((a, b) => b[1] - a[1])[0]?.[0] || 1
  );
  
  for (let n = (dominantDozen - 1) * 12 + 1; n <= dominantDozen * 12; n++) {
    masterData.suggestions.add(n);
  }
  
  const topMaster = Array.from(masterData.suggestions).slice(0, 12);
  console.log("✅ Master:", { targetDozen: dominantDozen, suggestions: topMaster.length });
  
  return {
    numbers: topMaster,
    dozen: dominantDozen,
    column: parseInt(
      Object.entries(masterData.column)
        .sort((a, b) => b[1] - a[1])[0]?.[0] || 1
    )
  };
};

// ============================================
// 6. CONVERGÊNCIA INTELIGENTE E PRECISA
// ============================================

const analyzeConvergence = (blockedNumbers, chainData, directData, patternsData, estelarData, masterData, maxNumbers) => {
  console.log("🎯 === CONVERGÊNCIA INTELIGENTE ===");
  
  const scores = {};
  for (let i = 0; i <= 36; i++) {
    scores[i] = { score: 0, reasons: [] };
  }
  
  // 1. CHAIN (PESO ALTÍSSIMO)
  chainData.numbers.forEach((num, idx) => {
    const points = (20 - idx) * 4.0;
    scores[num].score += points;
    scores[num].reasons.push(`Chain narrativo (+${points.toFixed(1)})`);
  });
  
  // 2. ANÁLISE DIRETA (PESO ALTÍSSIMO)
  directData.immediateNeighbors.forEach(num => {
    scores[num].score += 30.0;
    scores[num].reasons.push(`Vizinho imediato de ${directData.lastNumber} (+30.0)`);
  });
  
  directData.extendedNeighbors.forEach(num => {
    if (!directData.immediateNeighbors.includes(num)) {
      scores[num].score += 15.0;
      scores[num].reasons.push(`Vizinho 2º nível de ${directData.lastNumber} (+15.0)`);
    }
  });
  
  if (directData.mirror) {
    scores[directData.mirror].score += 25.0;
    scores[directData.mirror].reasons.push(`Espelho de ${directData.lastNumber} (+25.0)`);
  }
  
  directData.sectorNumbers.forEach(num => {
    scores[num].score += 12.0;
    scores[num].reasons.push(`Setor ${directData.sector} (+12.0)`);
  });
  
  directData.terminalFamily.forEach(num => {
    if (num !== directData.lastNumber) {
      scores[num].score += 8.0;
      scores[num].reasons.push(`Terminal ${getTerminal(directData.lastNumber)} (+8.0)`);
    }
  });
  
  // 3. PADRÕES RECENTES (PESO ALTO)
  patternsData.frequentNumbers.forEach((num, idx) => {
    const points = (8 - idx) * 3.0;
    scores[num].score += points;
    scores[num].reasons.push(`Frequente recente (+${points.toFixed(1)})`);
  });
  
  patternsData.frequentNeighbors.forEach(num => {
    scores[num].score += 10.0;
    scores[num].reasons.push('Cluster ativo (+10.0)');
  });
  
  patternsData.sequenceTargets.forEach(num => {
    scores[num].score += 12.0;
    scores[num].reasons.push('Sequência repetida (+12.0)');
  });
  
  // 4. ESTELAR (PESO MÉDIO)
  estelarData.numbers.forEach((num, idx) => {
    const points = (15 - idx) * 2.0;
    scores[num].score += points;
    scores[num].reasons.push(`Estelar (+${points.toFixed(1)})`);
  });
  
  // 5. MASTER (PESO MÉDIO)
  masterData.numbers.forEach((num, idx) => {
    const points = (12 - idx) * 2.5;
    scores[num].score += points;
    scores[num].reasons.push(`Master D${masterData.dozen} (+${points.toFixed(1)})`);
  });
  
  // 6. BÔNUS DE CONFLUÊNCIA (PESO MUITO ALTO)
  for (let num = 1; num <= 36; num++) {
    const sources = [];
    
    if (chainData.numbers.includes(num)) sources.push('Chain');
    
    if (directData.immediateNeighbors.includes(num) || 
        directData.extendedNeighbors.includes(num) || 
        directData.sectorNumbers.includes(num) ||
        num === directData.mirror) {
      sources.push('Direto');
    }
    
    if (patternsData.frequentNumbers.includes(num) || 
        patternsData.frequentNeighbors.has(num) ||
        patternsData.sequenceTargets.has(num)) {
      sources.push('Padrões');
    }
    
    if (estelarData.numbers.includes(num)) sources.push('Estelar');
    if (masterData.numbers.includes(num)) sources.push('Master');
    
    if (sources.length >= 2) {
      const bonus = sources.length * 20.0;
      scores[num].score += bonus;
      scores[num].reasons.push(`⭐ CONFLUÊNCIA x${sources.length} [${sources.join('+')}] (+${bonus})`);
    }
  }
  
  // 7. APLICAR BLOQUEIOS
  blockedNumbers.forEach(num => {
    if (scores[num].score > 0) {
      console.log(`  🚫 BLOQUEANDO ${num} (tinha ${scores[num].score.toFixed(1)} pts)`);
      scores[num].score = 0;
      scores[num].reasons = ['❌ BLOQUEADO: repetição/padrão inválido'];
    }
  });
  
  // ORDENAR E SELECIONAR
  const ranked = Object.entries(scores)
    .filter(([num]) => parseInt(num) !== 0)
    .map(([num, data]) => ({ num: parseInt(num), score: data.score, reasons: data.reasons }))
    .filter(item => item.score > 0)
    .sort((a, b) => b.score - a.score);
  
  console.log("📊 Top 15 números convergentes:");
  ranked.slice(0, 15).forEach(item => {
    console.log(`  ${item.num}: ${item.score.toFixed(1)} pts - ${item.reasons.slice(0, 3).join(', ')}`);
  });
  
  const selected = ranked.slice(0, maxNumbers).map(item => item.num);
  
  // TIPO DE ANÁLISE
  let analysisType = 'convergente';
  const topSources = new Set();
  ranked.slice(0, maxNumbers).forEach(item => {
    item.reasons.forEach(reason => {
      if (reason.includes('Chain')) topSources.add('Chain');
      if (reason.includes('Vizinho') || reason.includes('Espelho') || reason.includes('Setor')) topSources.add('Direto');
      if (reason.includes('Frequente') || reason.includes('Cluster') || reason.includes('Sequência')) topSources.add('Padrões');
      if (reason.includes('Estelar')) topSources.add('Estelar');
      if (reason.includes('Master')) topSources.add('Master');
    });
  });
  
  if (topSources.has('Chain') && topSources.size >= 2) {
    analysisType = 'chain';
  } else if (topSources.has('Direto') && topSources.size >= 2) {
    analysisType = 'estrutural_convergente';
  } else if (topSources.size >= 3) {
    analysisType = 'convergente';
  } else if (topSources.has('Estelar')) {
    analysisType = 'estelar';
  } else if (topSources.has('Master')) {
    analysisType = 'master';
  }
  
  // CONFIANÇA
  const avgScore = ranked.slice(0, maxNumbers).reduce((sum, item) => sum + item.score, 0) / maxNumbers;
  const topScore = ranked[0]?.score || 0;
  
  let confidence = 'média';
  if (topScore > 80 && avgScore > 60) {
    confidence = 'alta';
  } else if (topScore < 40 || avgScore < 30) {
    confidence = 'baixa';
  }
  
  // REASONING
  const topReasons = ranked[0]?.reasons || [];
  let reasoning = 'Análise multi-estratégica convergente';
  if (topReasons.length > 0) {
    const mainReason = topReasons[0];
    if (mainReason.includes('CONFLUÊNCIA')) {
      reasoning = `Convergência detectada. ${mainReason}`;
    } else {
      reasoning = mainReason.split('(+')[0].trim();
    }
  }
  
  console.log("✅ Convergência:", {
    selected,
    analysisType,
    confidence,
    avgScore: avgScore.toFixed(1),
    topSources: Array.from(topSources)
  });
  
  return {
    numbers: selected,
    sector: directData.sector || masterData.dozen,
    dozen: masterData.dozen,
    column: masterData.column,
    confidence,
    analysis_type: analysisType,
    sector_analysis: `C${Math.floor(Math.random() * 6) + 1}`,
    reasoning
  };
};

// ============================================
// FUNÇÃO PRINCIPAL
// ============================================

const analyzeRoulette = (history, maxNumbers = 6) => {
  if (history.length < 100) {
    throw new Error("Histórico insuficiente - mínimo 100 rodadas");
  }

  console.log("🎯 === ANÁLISE COMPLETA INTEGRADA ===");
  console.log(`📊 Histórico: ${history.length} rodadas | Último: ${history[0]}`);
  
  const blockedNumbers = checkBlockedNumbers(history);
  const chainData = analyzeChain(history);
  const directData = analyzeDirectNumber(history);
  const patternsData = analyzeRecentPatterns(history);
  const estelarData = analyzeEstelar(history);
  const masterData = analyzeMaster(history);
  
  const result = analyzeConvergence(
    blockedNumbers,
    chainData,
    directData,
    patternsData,
    estelarData,
    masterData,
    maxNumbers
  );
  
  console.log("✅ === ANÁLISE CONCLUÍDA ===");
  console.log(`🎯 Números: [${result.numbers.join(', ')}]`);
  console.log(`📈 Confiança: ${result.confidence} | Tipo: ${result.analysis_type}`);
  
  return result;
};

// ============================================
// COMPONENTE REACT
// ============================================

export default function Dashboard() {
  const [rouletteHistory, setRouletteHistory] = useState([]);
  const [currentSuggestion, setCurrentSuggestion] = useState(null);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [isLoadingHistory, setIsLoadingHistory] = useState(true);
  const [apiError, setApiError] = useState(null);
  const [numberOfDirectNumbers, setNumberOfDirectNumbers] = useState(6);
  const [lastGenerationTime, setLastGenerationTime] = useState(null);
  const [cooldownRemaining, setCooldownRemaining] = useState(0);
  const [subscriptionDays, setSubscriptionDays] = useState(null);
  const [showExpirationWarning, setShowExpirationWarning] = useState(false);
  const [confidenceData, setConfidenceData] = useState(null);
  const [isLoadingConfidence, setIsLoadingConfidence] = useState(false);
  const queryClient = useQueryClient();

  const historyCache = useRef([]);
  const confidenceCache = useRef(null);

  // Iniciar proteção anti-debug
  useEffect(() => {
    apiProtection.detectSuspiciousActivity();
    
    return () => {
      apiProtection.clearSensitiveData();
    };
  }, []);

  useEffect(() => {
    const checkSubscription = async () => {
      try {
        const user = await base44.auth.me();
        
        if (user.role === 'admin') {
          setSubscriptionDays(999);
          return;
        }

        const normalizedEmail = user.email.toLowerCase().trim();
        const allSubscribers = await base44.entities.Subscriber.list();
        const subscribers = allSubscribers.filter(sub => 
          sub.email.toLowerCase().trim() === normalizedEmail &&
          sub.status === 'active'
        );

        if (subscribers.length > 0) {
          const subscriber = subscribers[0];
          const expirationDate = new Date(subscriber.expiration_date);
          const now = new Date();
          expirationDate.setHours(0, 0, 0, 0);
          now.setHours(0, 0, 0, 0);
          const daysRemaining = differenceInDays(expirationDate, now);
          setSubscriptionDays(daysRemaining);
          
          if (daysRemaining <= 5 && daysRemaining > 0) {
            setShowExpirationWarning(true);
          }
        } else {
          setSubscriptionDays(0);
        }
      } catch (error) {
        console.error("Erro ao verificar assinatura:", error);
        setSubscriptionDays(0);
      }
    };

    checkSubscription();
  }, []);

  useEffect(() => {
    if (lastGenerationTime) {
      const checkCooldown = () => {
        const elapsed = Date.now() - lastGenerationTime;
        const remaining = Math.max(0, 30000 - elapsed);
        setCooldownRemaining(Math.ceil(remaining / 1000));
        
        if (remaining <= 0) {
          setLastGenerationTime(null);
        }
      };
      
      checkCooldown();
      const interval = setInterval(checkCooldown, 1000);
      return () => clearInterval(interval);
    }
  }, [lastGenerationTime]);

  useEffect(() => {
    const fetchRouletteHistory = async () => {
      try {
        if (!apiProtection.checkRateLimit(30, 60000)) {
          console.warn('Rate limit atingido');
          return;
        }
        
        if (!apiProtection.validateRequest()) {
          console.warn('Origem inválida');
        }
        
        const endpoint = getApiEndpoint();
        if (!endpoint) {
          throw new Error('Endpoint inválido');
        }
        
        const response = await fetch(endpoint, {
          headers: {
            'X-Client-Token': btoa(Date.now().toString()),
            'X-Session-ID': btoa(Math.random().toString(36)),
          }
        });
        
        if (!response.ok) {
          throw new Error(`Erro na API: ${response.status}`);
        }
        
        const data = await response.json();
        
        let historyData = [];
        if (Array.isArray(data)) {
          historyData = data;
        } else if (data.results && Array.isArray(data.results)) {
          historyData = data.results;
        } else {
          throw new Error("Formato de resposta inválido");
        }
        
        historyData = historyData.map(item => {
          if (typeof item === 'number') return item;
          if (typeof item === 'string') return parseInt(item, 10);
          if (typeof item === 'object' && item.number !== undefined) return parseInt(item.number, 10);
          return item;
        }).filter(num => !isNaN(num) && num >= 0 && num <= 36);
        
        const newHistory = historyData.slice(0, 200);
        
        const isDifferent = 
          historyCache.current.length !== newHistory.length ||
          historyCache.current[0] !== newHistory[0] ||
          JSON.stringify(historyCache.current.slice(0, 10)) !== JSON.stringify(newHistory.slice(0, 10));
        
        if (isDifferent) {
          console.log('🎰 Histórico atualizado! Novo número:', newHistory[0]);
          historyCache.current = newHistory;
          setRouletteHistory(newHistory);
        }
        
        setApiError(null);
        setIsLoadingHistory(false);
        
      } catch (error) {
        console.error("Erro ao buscar histórico:", error);
        setApiError(error.message);
        setIsLoadingHistory(false);
      }
    };

    fetchRouletteHistory();
    const interval = setInterval(fetchRouletteHistory, 10000);
    return () => clearInterval(interval);
  }, []);

  // Buscar dados de confiança quando o histórico mudar
  useEffect(() => {
    const fetchConfidenceData = async () => {
      if (rouletteHistory.length < 20) return;

      // Verificar se o histórico mudou significativamente
      const historyKey = rouletteHistory.slice(0, 20).join(',');
      if (confidenceCache.current?.key === historyKey) {
        return; // Cache ainda válido
      }

      setIsLoadingConfidence(true);

      try {
        const response = await fetch('/api/patterns/final-suggestion-batch', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            history: rouletteHistory,
            max_numbers: 18,
            confidence_threshold: 70,
            base_weight: 0.4,
            optimized_weight: 0.6,
          }),
        });

        if (!response.ok) {
          throw new Error(`Erro na API de confiança: ${response.status}`);
        }

        const data = await response.json();

        if (data.available && data.results) {
          // Criar mapa de posição -> dados de confiança
          const confidenceMap = {};
          data.results.forEach(item => {
            confidenceMap[item.position] = {
              number: item.number,
              finalConfidence: item.final_confidence,
              optimizedConfidence: item.optimized_confidence,
              legacyConfidence: item.legacy_confidence,
              finalSuggestion: item.final_suggestion,
              overlapRatio: item.overlap_ratio,
              isHighConfidence: item.final_confidence >= 70,
            };
          });

          const newConfidenceData = {
            key: historyKey,
            map: confidenceMap,
            highConfidencePositions: data.high_confidence_positions || [],
            totalAnalyzed: data.total_analyzed,
            highConfidenceCount: data.high_confidence_count,
          };

          confidenceCache.current = newConfidenceData;
          setConfidenceData(newConfidenceData);
          console.log(`🎯 Confiança calculada: ${data.high_confidence_count}/${data.total_analyzed} posições com >= 70%`);
        }
      } catch (error) {
        console.error('Erro ao buscar dados de confiança:', error);
      } finally {
        setIsLoadingConfidence(false);
      }
    };

    fetchConfidenceData();
  }, [rouletteHistory]);

  useEffect(() => {
    const checkPendingResults = async () => {
      if (rouletteHistory.length < 3) return;
      
      try {
        const pendingSuggestions = await base44.entities.Suggestion.filter({ result: 'pendente' });
        
        for (const suggestion of pendingSuggestions) {
          const snapshotNumbers = suggestion.history_snapshot || [];
          if (snapshotNumbers.length === 0) continue;

          const firstSnapshotNum = snapshotNumbers[0];
          const snapshotIndex = rouletteHistory.indexOf(firstSnapshotNum);
          
          if (snapshotIndex === -1) continue;
          
          const newNumbers = rouletteHistory.slice(0, snapshotIndex);
          
          if (newNumbers.length >= 3) {
            const recentNumbers = newNumbers.slice(0, 3);
            
            const numbersMatch = recentNumbers.some(num => suggestion.numbers.includes(num));
            const sectorNumbers = SECTORS[suggestion.sector] || [];
            const sectorMatch = recentNumbers.some(num => sectorNumbers.includes(num));
            const dozenMatch = recentNumbers.some(num => getDozen(num) === suggestion.dozen);
            const columnMatch = recentNumbers.some(num => getColumn(num) === suggestion.column);
            
            const matchTypes = [];
            if (numbersMatch) matchTypes.push('números');
            if (sectorMatch) matchTypes.push('setor');
            if (dozenMatch) matchTypes.push('dúzia');
            if (columnMatch) matchTypes.push('coluna');
            
            const isGreen = matchTypes.length > 0;
            
            let attemptsUsed = 3;
            if (isGreen) {
              for (let i = 0; i < recentNumbers.length; i++) {
                const num = recentNumbers[i];
                if (suggestion.numbers.includes(num) || 
                    sectorNumbers.includes(num) || 
                    getDozen(num) === suggestion.dozen || 
                    getColumn(num) === suggestion.column) {
                  attemptsUsed = i + 1;
                  break;
                }
              }
            }
            
            await base44.entities.Suggestion.update(suggestion.id, {
              result: isGreen ? 'green' : 'loss',
              result_numbers: recentNumbers,
              attempts_used: attemptsUsed,
              match_types: matchTypes.join(', ')
            });
            
            queryClient.invalidateQueries({ queryKey: ['suggestions'] });
          }
        }
      } catch (error) {
        console.error("Erro ao verificar resultados:", error);
      }
    };

    checkPendingResults();
  }, [rouletteHistory, queryClient]);

  const { data: suggestions = [], isLoading: loadingSuggestions } = useQuery({
    queryKey: ['suggestions'],
    queryFn: () => base44.entities.Suggestion.list('-created_date', 100),
  });

  const createSuggestionMutation = useMutation({
    mutationFn: (suggestionData) => base44.entities.Suggestion.create(suggestionData),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['suggestions'] });
    },
  });

  const handleGenerateSuggestion = async () => {
    if (subscriptionDays !== null && subscriptionDays <= 0 && subscriptionDays !== 999) {
      alert("Sua assinatura expirou. Por favor, renove para continuar usando o RoletaMestra PRO.");
      return;
    }

    if (rouletteHistory.length < 100) {
      alert("Histórico insuficiente. Necessário 100 rodadas.");
      return;
    }

    if (cooldownRemaining > 0) {
      alert(`Aguarde ${cooldownRemaining} segundos para gerar nova análise.`);
      return;
    }

    setIsAnalyzing(true);
    
    try {
      const analysis = analyzeRoulette(rouletteHistory, numberOfDirectNumbers);
      
      const analysisWithSnapshot = {
        ...analysis,
        history_snapshot: rouletteHistory.slice(0, 3),
        most_recent_number: rouletteHistory[0]
      };
      
      setCurrentSuggestion(analysisWithSnapshot);
      await createSuggestionMutation.mutateAsync(analysisWithSnapshot);
      setLastGenerationTime(Date.now());
    } catch (error) {
      console.error("Erro na análise:", error);
      alert(error.message || "Erro ao gerar sugestão");
    } finally {
      setIsAnalyzing(false);
    }
  };

  const completedSuggestions = suggestions.filter(s => s.result !== 'pendente');
  const greenSuggestions = completedSuggestions.filter(s => s.result === 'green');
  const winRate = completedSuggestions.length > 0 
    ? Math.round((greenSuggestions.length / completedSuggestions.length) * 100)
    : 0;

  const matchStats = {
    números: 0,
    setor: 0,
    dúzia: 0,
    coluna: 0
  };

  greenSuggestions.forEach(suggestion => {
    if (suggestion.match_types) {
      const types = suggestion.match_types.split(', ');
      types.forEach(type => {
        if (matchStats[type] !== undefined) {
          matchStats[type]++;
        }
      });
    }
  });

  const getSubscriptionBadge = () => {
    if (subscriptionDays === null) return null;
    if (subscriptionDays === 999) return null;
    
    if (subscriptionDays <= 0) {
      return (
        <Badge className="bg-red-600 text-white flex items-center gap-1 text-xs">
          <Clock className="w-3 h-3" />
          Expirada
        </Badge>
      );
    }
    
    if (subscriptionDays <= 5) {
      return (
        <Badge className="bg-yellow-600 text-black flex items-center gap-1 text-xs animate-pulse">
          <Calendar className="w-3 h-3" />
          {subscriptionDays} {subscriptionDays === 1 ? 'dia' : 'dias'}
        </Badge>
      );
    }
    
    if (subscriptionDays <= 10) {
      return (
        <Badge className="bg-orange-600 text-white flex items-center gap-1 text-xs">
          <Calendar className="w-3 h-3" />
          {subscriptionDays} dias
        </Badge>
      );
    }
    
    return (
      <Badge className="bg-green-600 text-white flex items-center gap-1 text-xs">
        <Calendar className="w-3 h-3" />
        {subscriptionDays} dias
      </Badge>
    );
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-black via-gray-900 to-black">
      <AnimatePresence>
        {showExpirationWarning && subscriptionDays !== null && subscriptionDays <= 5 && subscriptionDays > 0 && (
          <motion.div
            initial={{ opacity: 0, y: -50 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -50 }}
            className="fixed top-0 left-0 right-0 z-[101] bg-gradient-to-r from-yellow-900/95 to-red-900/95 border-b-2 border-yellow-500 backdrop-blur-lg shadow-2xl"
          >
            <div className="max-w-7xl mx-auto px-4 py-4">
              <div className="flex items-center justify-between gap-4">
                <div className="flex items-center gap-3">
                  <div className="bg-yellow-500 rounded-full p-2">
                    <AlertCircle className="w-6 h-6 text-black" />
                  </div>
                  <div>
                    <h3 className="text-white font-bold text-lg">⚠️ Sua assinatura está expirando!</h3>
                    <p className="text-yellow-200 text-sm">
                      Restam apenas <span className="font-bold text-white">{subscriptionDays} {subscriptionDays === 1 ? 'dia' : 'dias'}</span>. 
                      Renove agora para não perder o acesso ao RoletaMestra PRO.
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <a 
                    href="https://t.me/revesbet"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    <Button className="bg-yellow-500 hover:bg-yellow-600 text-black font-bold">
                      Renovar Agora
                    </Button>
                  </a>
                  <button
                    onClick={() => setShowExpirationWarning(false)}
                    className="text-white hover:text-gray-300 transition-colors"
                  >
                    <span className="text-2xl">×</span>
                  </button>
                </div>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      <div className="bg-gradient-to-r from-red-950/30 via-black to-cyan-950/30 border-b border-gray-800 backdrop-blur-sm">
        <div className="max-w-[1800px] mx-auto px-4 md:px-8 py-4">
          <div className="flex flex-col lg:flex-row justify-between items-start lg:items-center gap-4">
            <motion.div
              initial={{ opacity: 0, x: -20 }}
              animate={{ opacity: 1, x: 0 }}
            >
              <div className="flex items-center gap-3 mb-1">
                <h1 className="text-3xl md:text-4xl font-bold flex items-center gap-3">
                  <div className="w-12 h-12 bg-gradient-to-br from-red-600 via-yellow-500 to-cyan-500 rounded-full flex items-center justify-center shadow-lg shadow-yellow-500/50 animate-pulse">
                    <Target className="w-7 h-7 text-white" />
                  </div>
                  <span className="bg-gradient-to-r from-red-400 via-yellow-400 to-cyan-400 bg-clip-text text-transparent font-black">
                    RoletaMestra PRO
                  </span>
                </h1>
                {getSubscriptionBadge()}
              </div>
              <p className="text-gray-400 text-sm md:text-base font-medium">
                🔗 Chain + 🎯 Direto + 🔍 Padrões + ⭐ Estelar + 🎓 Master
              </p>
            </motion.div>

            {/* Botão de Assinatura com Desconto */}
            <motion.div
              initial={{ opacity: 0, scale: 0.9 }}
              animate={{ opacity: 1, scale: 1 }}
              transition={{ delay: 0.2 }}
              className="w-full lg:w-auto"
            >
              <a 
                href="https://lastlink.com/p/C8625940B/checkout-payment/"
                target="_blank"
                rel="noopener noreferrer"
                className="block"
              >
                <Button
                  size="lg"
                  className="w-full bg-gradient-to-r from-red-600 to-red-700 hover:from-red-700 hover:to-red-800 text-white font-bold shadow-lg shadow-red-500/50 border-2 border-red-400 animate-pulse transition-all duration-300 hover:scale-105"
                >
                  🔥 ASSINE O APLICATIVO 50% DE DESCONTO 🔥
                </Button>
              </a>
            </motion.div>
            
            <div className="flex flex-wrap gap-3 w-full lg:w-auto">
              <Button
                onClick={handleGenerateSuggestion}
                disabled={isAnalyzing || isLoadingHistory || rouletteHistory.length < 100 || cooldownRemaining > 0 || (subscriptionDays !== null && subscriptionDays <= 0 && subscriptionDays !== 999)}
                size="lg"
                className="flex-1 lg:flex-none bg-gradient-to-r from-yellow-500 to-yellow-600 hover:from-yellow-600 hover:to-yellow-700 text-black font-bold shadow-lg shadow-yellow-500/50 transition-all duration-300 hover:scale-105 disabled:opacity-50 border-2 border-yellow-400"
              >
                {isAnalyzing ? (
                  <>
                    <Loader2 className="w-5 h-5 mr-2 animate-spin" />
                    Analisando...
                  </>
                ) : cooldownRemaining > 0 ? (
                  <>
                    <Loader2 className="w-5 h-5 mr-2 animate-spin" />
                    {cooldownRemaining}s
                  </>
                ) : (subscriptionDays !== null && subscriptionDays <= 0 && subscriptionDays !== 999) ? (
                  <>
                    <AlertCircle className="w-5 h-5 mr-2" />
                    Assinatura Expirada
                  </>
                ) : (
                  <>
                    <Zap className="w-5 h-5 mr-2" />
                    Gerar Análise
                  </>
                )}
              </Button>

              <a 
                href="https://go.aff.esportiva.bet/utivunwn"
                target="_blank"
                rel="noopener noreferrer"
                className="flex-1 lg:flex-none"
              >
                <Button
                  size="lg"
                  className="w-full bg-gradient-to-r from-green-500 to-green-600 hover:from-green-600 hover:to-green-700 text-white font-bold shadow-lg shadow-green-500/50 transition-all duration-300 hover:scale-105 border-2 border-green-400"
                >
                  <TrendingUp className="w-5 h-5 mr-2" />
                  Acessar Mesa
                </Button>
              </a>
            </div>
          </div>
        </div>
      </div>
      
      {apiError && (
        <div className="max-w-[1800px] mx-auto px-4 md:px-8 mt-4">
          <motion.div
            initial={{ opacity: 0, y: -10 }}
            animate={{ opacity: 1, y: 0 }}
            className="bg-red-900/30 border border-red-500/50 rounded-xl p-4 backdrop-blur"
          >
            <div className="flex items-center gap-2 text-red-400">
              <AlertCircle className="w-5 h-5" />
              <span className="font-semibold">Erro na API:</span>
            </div>
            <p className="text-red-300 text-sm mt-1">{apiError}</p>
          </motion.div>
        </div>
      )}

      <div className="max-w-[1800px] mx-auto px-4 md:px-8 py-6">
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 md:gap-4">
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.1 }}
          >
            <Card className="bg-gradient-to-br from-gray-900 to-black border-gray-700 shadow-xl hover:shadow-cyan-500/20 transition-all">
              <CardHeader className="pb-2">
                <CardTitle className="text-xs md:text-sm font-medium text-cyan-400 flex items-center gap-2">
                  <History className="w-4 h-4" />
                  Histórico
                </CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-xl md:text-2xl font-bold text-white">
                  {rouletteHistory.length}
                  {rouletteHistory.length < 100 && (
                    <span className="text-xs text-yellow-500 block mt-1">Min: 100</span>
                  )}
                </p>
              </CardContent>
            </Card>
          </motion.div>

          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.2 }}
          >
            <Card className="bg-gradient-to-br from-gray-900 to-black border-gray-700 shadow-xl hover:shadow-purple-500/20 transition-all">
              <CardHeader className="pb-2">
                <CardTitle className="text-xs md:text-sm font-medium text-purple-400 flex items-center gap-2">
                  <TrendingUp className="w-4 h-4" />
                  Análises
                </CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-xl md:text-2xl font-bold text-white">{suggestions.length}</p>
                <p className="text-xs text-gray-400 mt-1">{completedSuggestions.length} concluídas</p>
              </CardContent>
            </Card>
          </motion.div>

          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.3 }}
          >
            <Card className="bg-gradient-to-br from-gray-900 to-black border-gray-700 shadow-xl hover:shadow-green-500/20 transition-all">
              <CardHeader className="pb-2">
                <CardTitle className="text-xs md:text-sm font-medium text-green-400 flex items-center gap-2">
                  <Sparkles className="w-4 h-4" />
                  Taxa
                </CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-xl md:text-2xl font-bold text-green-400">{winRate}%</p>
                <p className="text-xs text-gray-400 mt-1">{greenSuggestions.length}/{completedSuggestions.length}</p>
              </CardContent>
            </Card>
          </motion.div>

          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.4 }}
          >
            <Card className="bg-gradient-to-br from-gray-900 to-black border-gray-700 shadow-xl hover:shadow-yellow-500/20 transition-all">
              <CardHeader className="pb-2">
                <CardTitle className="text-xs md:text-sm font-medium text-yellow-400 flex items-center gap-2">
                  <Target className="w-4 h-4" />
                  Acertos
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-2 gap-1 text-xs">
                  <div><span className="text-blue-400">N:</span> {matchStats.números}</div>
                  <div><span className="text-purple-400">S:</span> {matchStats.setor}</div>
                  <div><span className="text-green-400">D:</span> {matchStats.dúzia}</div>
                  <div><span className="text-pink-400">C:</span> {matchStats.coluna}</div>
                </div>
              </CardContent>
            </Card>
          </motion.div>
        </div>
        
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          className="mt-4 bg-gray-900/50 border border-cyan-500/30 rounded-xl p-4 backdrop-blur"
        >
          <label htmlFor="num-direct-numbers" className="text-sm text-cyan-400 font-semibold mb-2 block flex items-center gap-2">
            <Target className="w-4 h-4" />
            Quantidade de Números Diretos: <span className="text-yellow-400 text-lg">{numberOfDirectNumbers}</span>
          </label>
          <input
            id="num-direct-numbers"
            type="range"
            min="1"
            max="12"
            value={numberOfDirectNumbers}
            onChange={(e) => setNumberOfDirectNumbers(parseInt(e.target.value))}
            className="w-full h-2 bg-gradient-to-r from-gray-700 via-cyan-600 to-gray-700 rounded-lg appearance-none cursor-pointer accent-cyan-500"
          />
          <div className="flex justify-between text-xs text-gray-400 mt-2">
            <span>Mínimo (1)</span>
            <span>Máximo (12)</span>
          </div>
        </motion.div>
      </div>

      <div className="max-w-[1800px] mx-auto px-4 md:px-8 pb-8">
        <div className="hidden lg:grid lg:grid-cols-12 gap-6">
          <div className="lg:col-span-3 space-y-6">
            <div className="bg-gradient-to-br from-gray-900 via-black to-gray-900 rounded-2xl p-4 border border-yellow-500/30 shadow-2xl shadow-yellow-500/10">
              <div className="h-[280px] flex items-center justify-center">
                <AnimatedWheel 
                  latestNumber={rouletteHistory[0]}
                  highlightedSector={currentSuggestion?.sector}
                  suggestedNumbers={currentSuggestion?.numbers || []}
                />
              </div>
            </div>
            
            <StatsDashboard history={rouletteHistory} />
          </div>
          
          <div className="lg:col-span-6 space-y-6">
            <AnimatePresence mode="wait">
              {currentSuggestion && (
                <SuggestionCard suggestion={currentSuggestion} />
              )}
            </AnimatePresence>
            
            <RouletteHistory
              history={rouletteHistory}
              isLoading={isLoadingHistory}
              confidenceData={confidenceData}
              isLoadingConfidence={isLoadingConfidence}
              confidenceThreshold={70}
            />
          </div>

          <div className="lg:col-span-3">
            <SuggestionHistory 
              suggestions={suggestions}
              isLoading={loadingSuggestions}
            />
          </div>
        </div>

        <div className="lg:hidden space-y-6">
          <AnimatePresence mode="wait">
            {currentSuggestion && (
              <SuggestionCard suggestion={currentSuggestion} />
            )}
          </AnimatePresence>
          
          <RouletteHistory
            history={rouletteHistory}
            isLoading={isLoadingHistory}
            confidenceData={confidenceData}
            isLoadingConfidence={isLoadingConfidence}
            confidenceThreshold={70}
          />

          <div className="bg-gradient-to-br from-gray-900 via-black to-gray-900 rounded-2xl p-4 border border-yellow-500/30 shadow-2xl shadow-yellow-500/10">
            <div className="h-[280px] flex items-center justify-center">
              <AnimatedWheel 
                latestNumber={rouletteHistory[0]}
                highlightedSector={currentSuggestion?.sector}
                suggestedNumbers={currentSuggestion?.numbers || []}
              />
            </div>
          </div>
          
          <StatsDashboard history={rouletteHistory} />
          
          <SuggestionHistory 
            suggestions={suggestions}
            isLoading={loadingSuggestions}
          />
        </div>
      </div>
    </div>
  );
}

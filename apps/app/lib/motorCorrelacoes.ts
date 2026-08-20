import 'server-only';

// MOTOR DE CORRELAÇÕES (web) — porte fiel do motor JavaScript embutido em
// "motor_correlacoes_monitor_api 2.html" (17/07/2026). A mesma calibração do
// motor_correlacoes.py (direta 3.0, terminal 2.5, espelho 1.5, confluência
// ×1.8, arrasto 0.75, meia-vida 300, profundidade 3) MAIS a camada de
// "realização concreta": classes de raiz digital com vagas (máx. 2/classe) e
// calor físico da roda quando o líder da classe está frio.
//
// PARIDADE: a saída precisa ser idêntica à do HTML (mesma ordem de operações
// de ponto flutuante, mesmos desempates). Não "melhorar" nada aqui sem rodar
// os fixtures de paridade contra o motor original extraído do HTML.
// Porte Python (worker de assertividade): apps/monitoring/scripts/motor_correlacoes_web.py

const WHEEL = [
  0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36, 11, 30, 8, 23, 10, 5, 24,
  16, 33, 1, 20, 14, 31, 9, 22, 18, 29, 7, 28, 12, 35, 3, 26,
];
const N = WHEEL.length;
const NUMBER_TO_WHEEL_INDEX = new Map(WHEEL.map((number, index) => [number, index]));

const FIXED_MIRRORS: Record<number, number> = {
  1: 10, 10: 1, 2: 20, 20: 2, 3: 30, 30: 3, 6: 9, 9: 6,
  12: 21, 21: 12, 13: 31, 31: 13, 14: 34, 34: 14,
  16: 19, 19: 16, 23: 32, 32: 23, 26: 29, 29: 26,
};
const TWINS = new Set([11, 22, 33]);
const HORSE_TERMINAL_GROUPS = [
  new Set([0, 3, 6, 9]),
  new Set([1, 4, 7]),
  new Set([2, 5, 8]),
];
const DIGITAL_ROOT_GROUPS: number[][] = [
  [0],
  [1, 10, 19, 28],
  [2, 11, 20, 29],
  [3, 12, 21, 30],
  [4, 13, 22, 31],
  [5, 14, 23, 32],
  [6, 15, 24, 33],
  [7, 16, 25, 34],
  [8, 17, 26, 35],
  [9, 18, 27, 36],
];
const NUMBER_TO_DIGITAL_ROOT = new Map<number, number>();
DIGITAL_ROOT_GROUPS.forEach((group, root) =>
  group.forEach((number) => NUMBER_TO_DIGITAL_ROOT.set(number, root)),
);

export interface EngineConfig {
  pullDepth: number;
  halfLife: number;
  patternOccurrences: number;
  directCutoff: number;
  directWeight: number;
  staircaseWeight: number;
  staircaseOpenFactor: number;
  activeTerminalWeight: number;
  pendingCutoff: number;
  pendingStrength: number;
  confluenceMultiplier: number;
  mirrorDragSources: number;
  mirrorDragFraction: number;
  fallbackFraction: number;
  channelWeights: Record<string, number>;
}

export const DEFAULT_ENGINE_CONFIG: EngineConfig = {
  pullDepth: 3,
  halfLife: 300,
  patternOccurrences: 4,
  directCutoff: 12,
  directWeight: 3.0,
  staircaseWeight: 0.7,
  staircaseOpenFactor: 0.7,
  activeTerminalWeight: 2.5,
  pendingCutoff: 5,
  pendingStrength: 0.8,
  confluenceMultiplier: 1.8,
  mirrorDragSources: 6,
  mirrorDragFraction: 0.75,
  fallbackFraction: 0.15,
  // Ordem dos canais importa para a paridade (soma de floats na mesma ordem).
  channelWeights: {
    terminal: 2.5,
    mirror: 1.5,
    twins: 1.5,
    digit_sum: 1.2,
    wheel_neighbor: 1.0,
    numeric_sequence: 1.0,
    horse: 0.4,
  },
};

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function digitalRoot(number: number): number {
  return NUMBER_TO_DIGITAL_ROOT.get(number)!;
}

function familyWheelNeighbor(number: number): number[] {
  const index = NUMBER_TO_WHEEL_INDEX.get(number)!;
  return [WHEEL[(index - 1 + N) % N], WHEEL[(index + 1) % N]];
}

function familyNumericSequence(number: number): number[] {
  const result: number[] = [];
  if (number - 1 >= 0) result.push(number - 1);
  if (number + 1 <= 36) result.push(number + 1);
  return result;
}

function familyTerminal(number: number): number[] {
  const terminal = number % 10;
  return Array.from({ length: 37 }, (_, candidate) => candidate)
    .filter((candidate) => candidate !== number && candidate % 10 === terminal);
}

function familyMirror(number: number): number[] {
  return FIXED_MIRRORS[number] === undefined ? [] : [FIXED_MIRRORS[number]];
}

function familyTwins(number: number): number[] {
  if (!TWINS.has(number)) return [];
  return [...TWINS].filter((candidate) => candidate !== number).sort((a, b) => a - b);
}

function familyDigitSum(number: number): number[] {
  return DIGITAL_ROOT_GROUPS[digitalRoot(number)].filter((candidate) => candidate !== number);
}

function familyHorse(number: number): number[] {
  const terminal = number % 10;
  const group = HORSE_TERMINAL_GROUPS.find((item) => item.has(terminal)) || new Set<number>();
  return Array.from({ length: 37 }, (_, candidate) => candidate)
    .filter((candidate) => candidate !== number && group.has(candidate % 10));
}

function families(number: number): Record<string, number[]> {
  return {
    terminal: familyTerminal(number),
    mirror: familyMirror(number),
    twins: familyTwins(number),
    digit_sum: familyDigitSum(number),
    wheel_neighbor: familyWheelNeighbor(number),
    numeric_sequence: familyNumericSequence(number),
    horse: familyHorse(number),
  };
}

function allRelatives(number: number): Set<number> {
  const result = new Set<number>();
  Object.values(families(number)).forEach((members) =>
    members.forEach((candidate) => result.add(candidate)),
  );
  result.delete(number);
  return result;
}

function circularDistanceNumbers(numberA: number, numberB: number): number {
  const indexA = NUMBER_TO_WHEEL_INDEX.get(numberA)!;
  const indexB = NUMBER_TO_WHEEL_INDEX.get(numberB)!;
  const difference = Math.abs(indexA - indexB);
  return Math.min(difference, N - difference);
}

function distanceKernel(distance: number, radius: number): number {
  if (distance > radius) return 0;
  if (radius === 0) return distance === 0 ? 1 : 0;
  return 1 - 0.75 * (distance / radius);
}

interface HeatConfig {
  heatWindow: number;
  heatHalfLife: number;
  heatRadius: number;
}

function localRegionHeats(historyNewestFirst: number[], config: HeatConfig): number[] {
  const recent = historyNewestFirst.slice(0, config.heatWindow);
  const heats = Array(37).fill(0);
  let normalizer = 0;
  recent.forEach((observed, age) => {
    const decay = Math.pow(0.5, age / config.heatHalfLife);
    normalizer += decay;
    for (let candidate = 0; candidate < 37; candidate += 1) {
      const distance = circularDistanceNumbers(observed, candidate);
      heats[candidate] += decay * distanceKernel(distance, config.heatRadius);
    }
  });
  if (normalizer > 0) {
    for (let number = 0; number < 37; number += 1) heats[number] /= normalizer;
  }
  return heats;
}

interface Profile {
  number: number;
  occurrenceCount: number;
  priorOccurrenceCount: number;
  pullStrengths: number[];
  firstPulls: number[];
  strength(candidate: number): number;
  rankedDirects(limit?: number | null): Array<[number, number]>;
}

function buildProfiles(numbersNewestFirst: number[], config: EngineConfig): Profile[] {
  const chronological = [...numbersNewestFirst].reverse();
  const length = chronological.length;
  const positions: number[][] = Array.from({ length: 37 }, () => []);
  const rawStrengths: number[][] = Array.from({ length: 37 }, () => Array(37).fill(0));
  const firstPullEvents: Array<Array<[number, number]>> = Array.from({ length: 37 }, () => []);

  chronological.forEach((source, occurrenceIndex) => {
    positions[source].push(occurrenceIndex);
    const age = (length - 1) - occurrenceIndex;
    const ageDecay = Math.pow(0.5, age / config.halfLife);

    if (occurrenceIndex + 1 < length) {
      firstPullEvents[source].push([occurrenceIndex, chronological[occurrenceIndex + 1]]);
    }

    for (let distance = 1; distance <= config.pullDepth; distance += 1) {
      const targetIndex = occurrenceIndex + distance;
      if (targetIndex >= length) break;
      const target = chronological[targetIndex];
      rawStrengths[source][target] += ageDecay / distance;
    }
  });

  return Array.from({ length: 37 }, (_, number) => {
    const occurrenceCount = positions[number].length;
    const denominator = Math.max(1, occurrenceCount);
    const pullStrengths = rawStrengths[number].map((value) => value / denominator);
    const firstPulls = firstPullEvents[number]
      .slice()
      .sort((a, b) => b[0] - a[0])
      .map((item) => item[1]);
    const priorOccurrenceCount = positions[number].filter((index) => index < length - 1).length;
    return {
      number,
      occurrenceCount,
      priorOccurrenceCount,
      pullStrengths,
      firstPulls,
      strength(candidate: number) { return pullStrengths[candidate]; },
      rankedDirects(limit: number | null = null) {
        const ranked = pullStrengths
          .map((strength, candidate) => [candidate, strength] as [number, number])
          .filter(([, strength]) => strength > 0)
          .sort((a, b) => (b[1] - a[1]) || (a[0] - b[0]));
        return limit === null ? ranked : ranked.slice(0, limit);
      },
    };
  });
}

export interface Contribution {
  component: string;
  points: number;
  reason: string;
}

function addContribution(
  scores: number[],
  contributions: Contribution[][],
  { base, candidate, points, component, reason }: {
    base: number; candidate: number; points: number; component: string; reason: string;
  },
): void {
  if (candidate === base || candidate < 0 || candidate > 36 || points <= 0) return;
  scores[candidate] += points;
  contributions[candidate].push({ component, points, reason });
}

function longestConsecutiveGroup(values: number[]): number[] {
  if (!values.length) return [];
  const unique = [...new Set(values)].sort((a, b) => a - b);
  const groups: number[][] = [];
  let current = [unique[0]];
  for (const value of unique.slice(1)) {
    if (value === current[current.length - 1] + 1) current.push(value);
    else { groups.push(current); current = [value]; }
  }
  groups.push(current);
  const candidates = groups.filter((group) => group.length >= 2);
  if (!candidates.length) return [];
  const recency = new Map([...new Set(values)].map((value) => [value, values.indexOf(value)]));
  candidates.sort((a, b) => {
    if (a.length !== b.length) return b.length - a.length;
    const recencyA = Math.min(...a.map((value) => recency.get(value)!));
    const recencyB = Math.min(...b.map((value) => recency.get(value)!));
    if (recencyA !== recencyB) return recencyA - recencyB;
    return a[0] - b[0];
  });
  return candidates[0];
}

function wheelFillOrder(base: number): number[] {
  const center = NUMBER_TO_WHEEL_INDEX.get(base)!;
  const result: number[] = [];
  for (let radius = 1; radius < N; radius += 1) {
    result.push(WHEEL[(center - radius + N) % N]);
    result.push(WHEEL[(center + radius) % N]);
  }
  return result;
}

export interface LogicalResult {
  base: number;
  behind: number | null;
  scores: number[];
  contributions: Contribution[][];
  rankingAll: number[];
  logicalTop: number[];
  cyclePaid: boolean;
  fallbackUsed: boolean;
  activeTerminals: number[];
  recentFirstPulls: number[];
  metadata: {
    historySize: number;
    baseOccurrences: number;
    basePriorOccurrences: number;
    channelStrengths: Record<string, number>;
    pendingNumbers: number[];
    mirrorSources: number[];
    confluenceFamilySize: number;
  };
}

export function runLogicalEngine(
  numbersNewestFirst: number[],
  outputSize: number,
  customConfig: Partial<EngineConfig> = {},
): LogicalResult {
  const config = { ...DEFAULT_ENGINE_CONFIG, ...customConfig };
  const base = numbersNewestFirst[0];
  const behind = numbersNewestFirst.length >= 2 ? numbersNewestFirst[1] : null;
  const profiles = buildProfiles(numbersNewestFirst, config);
  const baseProfile = profiles[base];
  const scores = Array(37).fill(0);
  const contributions: Contribution[][] = Array.from({ length: 37 }, () => []);
  const recentFirstPulls = baseProfile.firstPulls.slice(0, config.patternOccurrences);
  const fallbackUsed = baseProfile.priorOccurrenceCount === 0;
  let activeTerminals: number[] = [];
  let channelStrengths: Record<string, number> = {};

  if (fallbackUsed) {
    const baseFamilies = families(base);
    Object.entries(config.channelWeights).forEach(([channel, weight]) => {
      const points = weight * config.fallbackFraction;
      baseFamilies[channel].forEach((candidate) => addContribution(scores, contributions, {
        base, candidate, points,
        component: `fallback_${channel}`,
        reason: `fallback do base ${base}: canal ${channel}, 15% do peso ${weight.toFixed(2)}`,
      }));
    });
  } else {
    const rankedDirects = baseProfile.rankedDirects()
      .filter(([candidate]) => candidate !== base)
      .slice(0, config.directCutoff);
    rankedDirects.forEach(([candidate, strength]) => {
      const points = config.directWeight * strength;
      addContribution(scores, contributions, {
        base, candidate, points,
        component: 'direct',
        reason: `puxada direta do base ${base}: força ${strength.toFixed(6)} × ${config.directWeight.toFixed(2)}`,
      });
    });

    if (recentFirstPulls.length) {
      const confirmed = longestConsecutiveGroup(recentFirstPulls);
      if (confirmed.length) {
        [confirmed[0] - 1, confirmed[confirmed.length - 1] + 1].forEach((candidate) => {
          addContribution(scores, contributions, {
            base, candidate, points: config.staircaseWeight,
            component: 'staircase_confirmed',
            reason: `escada confirmada do base ${base}: puxou [${confirmed.join(', ')}], ponta ${candidate}`,
          });
        });
      } else {
        const anchor = recentFirstPulls[0];
        const points = config.staircaseWeight * config.staircaseOpenFactor;
        [anchor - 1, anchor + 1].forEach((candidate) => {
          addContribution(scores, contributions, {
            base, candidate, points,
            component: 'staircase_open',
            reason: `escada aberta do base ${base}: âncora ${anchor}, ponta ${candidate}`,
          });
        });
      }
    }

    if (recentFirstPulls.length >= 2) {
      const terminalCounts = new Map<number, number>();
      recentFirstPulls.forEach((value) =>
        terminalCounts.set(value % 10, (terminalCounts.get(value % 10) || 0) + 1),
      );
      activeTerminals = [...terminalCounts.entries()]
        .filter(([, count]) => count >= 2)
        .map(([terminal]) => terminal)
        .sort((a, b) => a - b);
      const excluded = new Set(recentFirstPulls);
      activeTerminals.forEach((terminal) => {
        for (let candidate = 0; candidate < 37; candidate += 1) {
          if (candidate % 10 === terminal && !excluded.has(candidate) && candidate !== base) {
            addContribution(scores, contributions, {
              base, candidate, points: config.activeTerminalWeight,
              component: 'active_terminal_pattern',
              reason: `terminal ${terminal} ativo nas últimas puxadas [${recentFirstPulls.join(', ')}] do base ${base}`,
            });
          }
        }
      });
    }

    const baseFamilies = families(base);
    Object.entries(config.channelWeights).forEach(([channel, weight]) => {
      const members = baseFamilies[channel];
      const observedStrength = members.reduce((sum, member) => sum + baseProfile.strength(member), 0);
      channelStrengths[channel] = observedStrength;
      if (observedStrength <= 0) return;
      const points = weight * observedStrength;
      members.forEach((candidate) => addContribution(scores, contributions, {
        base, candidate, points,
        component: `hot_channel_${channel}`,
        reason: `canal ${channel} do base ${base}: força ${observedStrength.toFixed(6)} × peso ${weight.toFixed(2)}`,
      }));
    });
  }

  if (fallbackUsed) {
    channelStrengths = Object.fromEntries(
      Object.keys(config.channelWeights).map((channel) => [channel, 0]),
    );
  }

  let cyclePaid = false;
  const pendingNumbers: number[] = [];
  let confluenceFamilySize = 0;

  if (behind !== null) {
    const behindProfile = profiles[behind];
    const wideFamily = new Set<number>();
    behindProfile.pullStrengths.forEach((strength, number) => {
      if (strength > 0) wideFamily.add(number);
    });
    allRelatives(behind).forEach((number) => wideFamily.add(number));
    wideFamily.delete(behind);
    confluenceFamilySize = wideFamily.size;
    [...wideFamily].sort((a, b) => a - b).forEach((candidate) => {
      if (candidate === base || scores[candidate] <= 0) return;
      const previous = scores[candidate];
      const next = previous * config.confluenceMultiplier;
      const delta = next - previous;
      scores[candidate] = next;
      contributions[candidate].push({
        component: 'confluence',
        points: delta,
        reason: `confluência: trás ${behind} puxa a mesma família (×${config.confluenceMultiplier.toFixed(2)})`,
      });
    });

    const topDirects = behindProfile.rankedDirects(config.pendingCutoff);
    cyclePaid = topDirects.some(([candidate]) => candidate === base);
    if (!cyclePaid) {
      topDirects.forEach(([candidate, strength]) => {
        const points = config.pendingStrength * strength;
        addContribution(scores, contributions, {
          base, candidate, points,
          component: 'behind_pending',
          reason: `pendência do trás ${behind}: força ${strength.toFixed(6)} × ${config.pendingStrength.toFixed(2)}`,
        });
        pendingNumbers.push(candidate);
      });
    }
  }

  const mirrorSources = Array.from({ length: 37 }, (_, number) => number)
    .filter((number) => number !== base && scores[number] > 0)
    .sort((a, b) => (scores[b] - scores[a]) || (a - b))
    .slice(0, config.mirrorDragSources);
  const mirrorSnapshot = new Map(mirrorSources.map((number) => [number, scores[number]]));
  mirrorSources.forEach((source) => {
    const mirror = FIXED_MIRRORS[source];
    if (mirror === undefined || mirror === base) return;
    const points = mirrorSnapshot.get(source)! * config.mirrorDragFraction;
    addContribution(scores, contributions, {
      base, candidate: mirror, points,
      component: 'mirror_drag',
      reason: `arrasto de espelho: ${source} arrasta ${mirror} com 75% de ${mirrorSnapshot.get(source)!.toFixed(6)}`,
    });
  });

  scores[base] = 0;
  contributions[base] = [];

  const rankingAll = Array.from({ length: 37 }, (_, number) => number)
    .filter((number) => number !== base)
    .sort((a, b) => (scores[b] - scores[a]) || (a - b));
  const positiveRanking = rankingAll.filter((number) => scores[number] > 0);
  const selected = positiveRanking.slice(0, outputSize);
  const selectedSet = new Set(selected);
  if (selected.length < outputSize) {
    for (const candidate of wheelFillOrder(base)) {
      if (candidate === base || selectedSet.has(candidate)) continue;
      selected.push(candidate);
      selectedSet.add(candidate);
      contributions[candidate].push({
        component: 'wheel_fill',
        points: 0,
        reason: `preenchimento por vizinhança física do base ${base}`,
      });
      if (selected.length === outputSize) break;
    }
  }

  return {
    base,
    behind,
    scores,
    contributions,
    rankingAll,
    logicalTop: selected,
    cyclePaid,
    fallbackUsed,
    activeTerminals,
    recentFirstPulls,
    metadata: {
      historySize: numbersNewestFirst.length,
      baseOccurrences: baseProfile.occurrenceCount,
      basePriorOccurrences: baseProfile.priorOccurrenceCount,
      channelStrengths,
      pendingNumbers,
      mirrorSources,
      confluenceFamilySize,
    },
  };
}

interface AllocationConfig {
  maxSlotsPerGroup: number;
  groupScoreMode: 'sum' | 'max';
  heatWeight: number;
  coldOnly: boolean;
  coldRatioThreshold: number;
  heatWindow: number;
  heatHalfLife: number;
  heatRadius: number;
  outputSize: number;
}

export interface AllocationResult {
  concreteTop: number[];
  allocations: Map<number, number>;
  groupScores: Map<number, number>;
  memberUtilities: Map<number, number>;
  memberPriorities: Map<number, number>;
  groupLeaders: Map<number, number>;
  heatEnabledByRoot: Map<number, boolean>;
  localHeats: number[];
}

export function allocateGroupSlots(
  scores: number[],
  historyNewestFirst: number[],
  base: number,
  config: AllocationConfig,
): AllocationResult {
  const cleanScores = scores.map((value) => Math.max(0, Number(value) || 0));
  const heats = localRegionHeats(historyNewestFirst, config);
  const eligibleByRoot = new Map<number, number[]>();
  const groupScores = new Map<number, number>();
  const memberUtilities = new Map<number, number>();
  const groupLeaders = new Map<number, number>();
  const heatEnabledByRoot = new Map<number, boolean>();

  DIGITAL_ROOT_GROUPS.forEach((group, root) => {
    const eligible = group.filter((number) => number !== base);
    if (!eligible.length) return;
    eligibleByRoot.set(root, eligible);
    const values = eligible.map((number) => cleanScores[number]);
    const groupScore = config.groupScoreMode === 'max'
      ? Math.max(...values)
      : values.reduce((sum, value) => sum + value, 0);
    groupScores.set(root, groupScore);
    const maxSpecific = Math.max(...values, 0) || 1;
    const maxHeat = Math.max(...eligible.map((number) => heats[number]), 0) || 1;
    const leader = eligible.slice().sort((a, b) => (cleanScores[b] - cleanScores[a]) || (a - b))[0];
    groupLeaders.set(root, leader);
    const leaderHeatRatio = heats[leader] / maxHeat;
    const useHeat = !config.coldOnly || leaderHeatRatio < config.coldRatioThreshold;
    heatEnabledByRoot.set(root, useHeat);
    const heatWeight = useHeat ? config.heatWeight : 0;
    eligible.forEach((number) => {
      const specific = cleanScores[number] / maxSpecific;
      const physical = heats[number] / maxHeat;
      memberUtilities.set(number, (1 - heatWeight) * specific + heatWeight * physical);
    });
  });

  const allocations = new Map([...eligibleByRoot.keys()].map((root) => [root, 0]));
  for (let slot = 0; slot < config.outputSize; slot += 1) {
    const candidates = [...eligibleByRoot.entries()]
      .filter(([root, eligible]) =>
        allocations.get(root)! < Math.min(config.maxSlotsPerGroup, eligible.length) &&
        groupScores.get(root)! > 0)
      .map(([root]) => root);
    if (!candidates.length) break;
    candidates.sort((a, b) => {
      const quotientA = groupScores.get(a)! / (allocations.get(a)! + 1);
      const quotientB = groupScores.get(b)! / (allocations.get(b)! + 1);
      return (quotientB - quotientA) || (a - b);
    });
    allocations.set(candidates[0], allocations.get(candidates[0])! + 1);
  }

  let selected: number[] = [];
  for (const [root, slots] of allocations.entries()) {
    if (slots <= 0) continue;
    const members = eligibleByRoot.get(root)!.slice().sort((a, b) => {
      const utilityDifference = memberUtilities.get(b)! - memberUtilities.get(a)!;
      if (utilityDifference) return utilityDifference;
      const scoreDifference = cleanScores[b] - cleanScores[a];
      return scoreDifference || (a - b);
    });
    selected.push(...members.slice(0, slots));
  }

  const memberPriorities = new Map<number, number>();
  for (const [number, utility] of memberUtilities.entries()) {
    memberPriorities.set(number, groupScores.get(digitalRoot(number))! * utility);
  }
  selected = [...new Set(selected)].sort((a, b) => {
    const priorityDifference = memberPriorities.get(b)! - memberPriorities.get(a)!;
    if (priorityDifference) return priorityDifference;
    const scoreDifference = cleanScores[b] - cleanScores[a];
    return scoreDifference || (a - b);
  });

  if (selected.length < config.outputSize) {
    const remaining = Array.from({ length: 37 }, (_, number) => number)
      .filter((number) => number !== base && !selected.includes(number))
      .sort((a, b) => (cleanScores[b] - cleanScores[a]) || (a - b));
    selected.push(...remaining.slice(0, config.outputSize - selected.length));
  }

  return {
    concreteTop: selected.slice(0, config.outputSize),
    allocations,
    groupScores,
    memberUtilities,
    memberPriorities,
    groupLeaders,
    heatEnabledByRoot,
    localHeats: heats,
  };
}

export interface MotorOptions {
  outputSize: number;
  maxSlotsPerGroup: number;
  heatWeight: number;
  coldRatioThreshold: number;
  heatWindow: number;
  coldOnly: boolean;
}

// Defaults idênticos à UI do HTML (9 sugestões, modo concreto, máx. 2 por
// classe, calor 0.25 só com líder frio < 0.70, janela de calor 36).
export const MOTOR_DEFAULT_OPTIONS: MotorOptions = {
  outputSize: 9,
  maxSlotsPerGroup: 2,
  heatWeight: 0.25,
  coldRatioThreshold: 0.7,
  heatWindow: 36,
  coldOnly: true,
};

// Mesmo limite de histórico do monitor do HTML ("Números do histórico": 300).
export const MOTOR_HISTORY_LIMIT = 300;

export interface MotorResult {
  logical: LogicalResult;
  allocation: AllocationResult;
  concreteTop: number[];
}

export function analyzeHistory(
  numbers: number[],
  options: MotorOptions = MOTOR_DEFAULT_OPTIONS,
): MotorResult {
  const count = clamp(Math.trunc(options.outputSize), 1, 36);
  const logical = runLogicalEngine(numbers, count);
  const allocation = allocateGroupSlots(logical.scores, numbers, logical.base, {
    maxSlotsPerGroup: clamp(Math.trunc(options.maxSlotsPerGroup), 1, 4),
    groupScoreMode: 'sum',
    heatWeight: clamp(Number(options.heatWeight), 0, 1),
    coldOnly: Boolean(options.coldOnly),
    coldRatioThreshold: clamp(Number(options.coldRatioThreshold), 0, 1),
    heatWindow: clamp(Math.trunc(options.heatWindow), 4, 500),
    heatHalfLife: 18,
    heatRadius: 3,
    outputSize: count,
  });

  return { logical, allocation, concreteTop: allocation.concreteTop };
}

/**
 * Sugestão do motor no formato usado pela rota: 9 números concretos (padrão do
 * HTML) + ranking lógico e contexto. `numbers` mais-recente-primeiro; requer
 * pelo menos 2 números (mesma exigência do monitor do HTML).
 */
export function motorSuggestion(numbersNewestFirst: number[]): {
  concrete: number[];
  logical: number[];
  base: number;
  behind: number | null;
  cyclePaid: boolean;
  activeTerminals: number[];
} | null {
  const valid = numbersNewestFirst.filter(
    (x) => Number.isInteger(x) && x >= 0 && x <= 36,
  );
  if (valid.length < 2) return null;
  const result = analyzeHistory(valid, MOTOR_DEFAULT_OPTIONS);
  return {
    concrete: result.concreteTop,
    logical: result.logical.logicalTop,
    base: result.logical.base,
    behind: result.logical.behind,
    cyclePaid: result.logical.cyclePaid,
    activeTerminals: result.logical.activeTerminals,
  };
}

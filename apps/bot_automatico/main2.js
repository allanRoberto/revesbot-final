/* const { analyzeWheelRegions } = require("./analyze");

const history2 = [
    19,
    0,
    ...
  ];
  
  const r2 = analyzeWheelRegions(history2);
  
  console.log("Padrão:", r2.pattern);
  console.log("Região recomendada:", r2.recommended);
  console.log("Regiões (resumido):", r2.regions.map(r => ({
    id: r.id,
    center: r.center,
    membership: r.membershipRatio.toFixed(2),
    lastDist: r.lastHitDist
  }))); */

const { analyzeWheelRegionsV2 } = require('./analyze_v2');

// history: mais recente no índice 0
const history = [
    14,
23,
10,
16,
35,
29,
18,
    26,
    6,
0,
33,
23,
18,
24,
17,
0,
10,
6,
23,
19,
25,
20,
12,
25,
28,
11,
15,
5,
30,
14,
19,
33,
33,
10,
4,
8,
7,
19,
35,
17,
10,
34,
12,
34,
25,
19,
18,
15
];

const analise = analyzeWheelRegionsV2(history, {
  windowSize: 30,
  radius: 3
});

console.log(analise.clarity, analise.pattern);
console.log('Core:', analise.coreNumbers);
console.log('Extended:', analise.extendedNumbers);
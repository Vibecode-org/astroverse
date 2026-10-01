// Утилиты
export * from './utils/celestialUtils.js';
export * from './utils/coordinates.js';
export * from './utils/colorUtils.js';
export * from './utils/hash.js';
export * from './helpers/index.js';
export * from './solarLayout.js';

// Текстуры
export * from './textures/starTextures.js';
export * from './textures/nebulaTextures.js';
export * from './textures/bodyTextures.js';

// Меши
export * from './meshes/blackHoleMesh.js';
export * from './meshes/nebulaMesh.js';
export * from './meshes/clusterMesh.js';
export * from './meshes/galaxyMesh.js';
export * from './meshes/milkyWayMesh.js';
export * from './meshes/starPlanetMesh.js';

// Главная функция создания меша
export { createBodyMesh } from './createBodyMesh.js';

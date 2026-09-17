// Утилиты
export * from './utils/celestialUtils.js';
export * from './helpers/index.js';

// Текстуры
export * from './textures/starTextures.js';
export * from './textures/nebulaTextures.js';

// Меши
export * from './meshes/blackHoleMesh.js';
export * from './meshes/nebulaMesh.js';
export * from './meshes/clusterMesh.js';
export * from './meshes/galaxyMesh.js';
export * from './meshes/starPlanetMesh.js';

// Главная функция создания меша
export { createBodyMesh } from './createBodyMesh.js';
import * as THREE from 'three';
import { createBlackHoleMesh } from './meshes/blackHoleMesh.js';
import { createNebulaMesh } from './meshes/nebulaMesh.js';
import { createClusterMesh } from './meshes/clusterMesh.js';
import { createGalaxyMesh } from './meshes/galaxyMesh.js';
import { createStarPlanetMesh } from './meshes/starPlanetMesh.js';

export function createBodyMesh(obj) {
  const isBlackHole = obj.kind === 'black_hole';
  const isNebula = obj.kind === 'nebula';
  const isCluster = obj.kind === 'cluster';
  const isGalaxy = obj.kind === 'galaxy';
  const isStar = obj.kind === 'star';

  if (isBlackHole) {
    return createBlackHoleMesh(obj);
  }
  
  if (isNebula) {
    return createNebulaMesh(obj);
  }
  
  if (isCluster) {
    return createClusterMesh(obj);
  }
  
  if (isGalaxy) {
    return createGalaxyMesh(obj);
  }
  
  return createStarPlanetMesh(obj);
}
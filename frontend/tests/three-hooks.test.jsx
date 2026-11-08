import React from 'react';
import { render, renderHook } from '@testing-library/react';
import { beforeEach, expect, test, vi } from 'vitest';
import * as THREE from 'three';
import { createStage } from '../src/scene/stage.js';
import { startAnimationLoop } from '../src/scene/animation.js';
import { useThree } from '../src/hooks/useThree.js';
import { useThreeScene } from '../src/hooks/useThreeScene.js';
import { useThreeView } from '../src/hooks/useThreeView.js';
import { useThreeFollow } from '../src/hooks/useThreeFollow.js';
import { useThreeTime } from '../src/hooks/useThreeTime.js';

vi.mock('../src/scene/stage.js', () => ({ createStage: vi.fn() }));
vi.mock('../src/scene/animation.js', () => ({ startAnimationLoop: vi.fn() }));

function state() {
  return { scene: new THREE.Scene(), camera: new THREE.PerspectiveCamera(),
    system: new THREE.Group(), nearby: new THREE.Group(), galaxy: { group: new THREE.Group() },
    galaxyMarkers: new THREE.Group(), ambient: {}, sunLight: {},
    meshes: new Map(), controls: { target: new THREE.Vector3(), update: vi.fn() } };
}

let stage;
beforeEach(() => {
  stage = { ...state(), renderer: { domElement: document.createElement('canvas'),
    setSize: vi.fn(), dispose: vi.fn() }, focusLight: {},
    controls: { target: new THREE.Vector3(), update: vi.fn(), dispose: vi.fn() } };
  createStage.mockImplementation(() => stage);
  startAnimationLoop.mockImplementation(() => vi.fn());
});

test('view hook repositions each scale, resets follow and tolerates absent scene', () => {
  const appRef = { current: state() }, objects = [];
  const { rerender } = renderHook(({ view }) => useThreeView({ view, objects, appRef, solarScale: 'real' }),
    { initialProps: { view: 'solar' } });
  expect(appRef.current.camera.position.toArray()).toEqual([0, 90000, 160000]);
  rerender({ view: 'local' }); expect(appRef.current.camera.position.toArray()).toEqual([0, 35, 70]);
  rerender({ view: 'galaxy' }); expect(appRef.current.camera.position.toArray()).toEqual([0, 220, 350]);
  appRef.current.limits = { solarCam: [1, 2, 3] };
  rerender({ view: 'solar' }); expect(appRef.current.camera.position.toArray()).toEqual([1, 2, 3]);
  appRef.current = {}; rerender({ view: 'local' });
});

test('follow hook uses world coordinates, supports large bodies and releases selection pins', () => {
  const appRef = { current: state() }, objects = [], setView = vi.fn(), setFollow = vi.fn();
  const mesh = new THREE.Object3D(); mesh.position.set(10, 20, 30); mesh.userData.displayRadius = 2;
  appRef.current.meshes.set('a', mesh);
  appRef.current.lod = { ensureL2: vi.fn(), releaseL2: vi.fn() };
  const hook = renderHook(({ selected, follow }) => useThreeFollow({ selected, follow,
    objects, appRef, setView, setFollow }), { initialProps: { selected: { id: 'a', kind: 'star' }, follow: true } });
  expect(appRef.current.controls.target.toArray()).toEqual([10, 20, 30]);
  expect(appRef.current.camera.position.x).toBeCloseTo(15.6);
  hook.rerender({ selected: { id: 'a', kind: 'galaxy' }, follow: false });
  expect(appRef.current.camera.position.x).toBeCloseTo(18.4);
  expect(appRef.current.followCamera).toBe(false);
  hook.rerender({ selected: null, follow: false });
  expect(appRef.current.lod.releaseL2).toHaveBeenCalled();
  hook.rerender({ selected: { id: 'missing' }, follow: false });
  appRef.current = {}; hook.rerender({ selected: null, follow: false });
});

test('time hook writes the exact timestamp and responds to date changes', () => {
  const appRef = { current: {} }, objects = [];
  const { rerender } = renderHook(({ time }) => useThreeTime({ simDate: new Date(time), objects, appRef }),
    { initialProps: { time: 0 } });
  expect(appRef.current.simTime).toBe(0); rerender({ time: -100 }); expect(appRef.current.simTime).toBe(-100);
});

test.each(['compact', 'real', 'unknown'])('scene mounts once for %s, resizes and cleans up', solarScale => {
  const objects = [{ id: 'sun', name: 'Sun', kind: 'star', scale: 'solar' }];
  const appRef = { current: {} }, onPick = vi.fn(), setErrorDetails = vi.fn();
  function Harness({ time }) {
    const { mountRef } = useThreeScene({ objects, solarScale, appRef, onPick, setErrorDetails, simDate: new Date(time) });
    return <div ref={mountRef} />;
  }
  const { rerender, unmount } = render(<Harness time={0} />);
  expect(appRef.current.scene).toBe(stage.scene);
  rerender(<Harness time={100} />); expect(createStage).toHaveBeenCalledTimes(1);
  window.dispatchEvent(new Event('resize')); expect(stage.renderer.setSize).toHaveBeenCalled();
  unmount(); expect(appRef.current).toEqual({});
  expect(stage.renderer.dispose).toHaveBeenCalled(); expect(stage.controls.dispose).toHaveBeenCalled();
  expect(setErrorDetails).not.toHaveBeenCalled();
});

test('partial scene initialization failure cleans resources and reports a recoverable error', () => {
  vi.spyOn(console, 'error').mockImplementation(() => {});
  startAnimationLoop.mockImplementationOnce(() => { throw new Error('animation init'); });
  const appRef = { current: {} }, setErrorDetails = vi.fn(), objects = [{ id: 'a', name: 'a', kind: 'star', scale: 'local' }];
  function Harness() {
    const { mountRef } = useThreeScene({ objects, solarScale: 'compact', appRef,
      onPick: vi.fn(), setErrorDetails, simDate: new Date(0) });
    return <div ref={mountRef} />;
  }
  render(<Harness />);
  expect(setErrorDetails).toHaveBeenCalledWith(expect.stringContaining('animation init'));
  expect(stage.renderer.dispose).toHaveBeenCalled(); expect(appRef.current).toEqual({});
});

test('main hook composes scene/time/follow and routes canvas selections into React setters', () => {
  const appRef = { current: {} }, setView = vi.fn(), setSelected = vi.fn(), setFollow = vi.fn();
  const options = { appRef, setView, setSelected, setFollow, objects: [{ id: 'a', name: 'a', kind: 'star', scale: 'local' }],
    selected: null, follow: false, simDate: new Date(0), setErrorDetails: vi.fn(), view: 'local', solarScale: 'compact' };
  function Harness() { const { mountRef } = useThree(options); return <div ref={mountRef} />; }
  const { unmount } = render(<Harness />);
  const el = stage.renderer.domElement;
  Object.defineProperty(el, 'clientHeight', { value: 1000 });
  el.getBoundingClientRect = () => ({ width: 1000, height: 1000, left: 0, top: 0 });
  appRef.current.lod.pick = () => options.objects[0];
  el.dispatchEvent(new MouseEvent('pointerdown')); el.dispatchEvent(new MouseEvent('pointerup'));
  expect(setView).toHaveBeenCalledWith('local'); expect(setSelected).toHaveBeenCalledWith(options.objects[0]);
  expect(setFollow).toHaveBeenCalledWith(true); unmount();
  renderHook(() => useThree({ ...options, objects: [] }));
});

import { describe,it,expect,vi } from 'vitest';
import * as THREE from 'three';
import fixture from '../../tests/fixtures/physical_hierarchy_synthetic.json';
import horizons from '../../tests/fixtures/horizons_centers.json';
import { PhysicalHierarchy } from '../src/physical/hierarchy.js';
import { physicalFrame,renderPosition,verifiedRows } from '../src/physical/coordinates.js';
import { createPhysicalLayer } from '../src/physical/PhysicalScene.jsx';
const copy = () => structuredClone(fixture.frame);

function repartition(frame) {
  for(const [id,placement] of Object.entries(fixture.repartition)) Object.assign(frame.hierarchy.bodies.find(b=>b.id===id),placement);
  return frame;
}

describe('physical coordinate charts (synthetic data, no NASA claims)',()=>{
  it('resolves sector/system/body charts against hand-calculated independent vectors',()=>{
    const frame=copy(),graph=new PhysicalHierarchy(frame);
    for(const row of frame.objects) expect(graph.absolute(row.id)).toEqual(row.position);
    for(const [pair,expected] of Object.entries(fixture.relative)) {
      const [body,origin]=pair.split(':');
      expect(graph.relative(body,origin)).toEqual(expected);
      expect(graph.relative(origin,body)).toEqual(expected.map(v=>-v));
    }
    expect(graph.relative('a','a')).toEqual([0,0,0]);
    expect(graph.address('a')).toEqual({id:'a',system_id:'sys1',sector_id:'s1'});
    expect(graph.absolute('missing')).toBe(null);expect(graph.address('missing')).toBe(null);
    expect(graph.relative('missing','a')).toBe(null);expect(graph.relative('a','unknown')).toBe(null);
    frame.hierarchy.bodies[0].offset_km[0]=999;
    expect(graph.absolute('a')).toEqual(fixture.frame.objects[0].position);
  });
  it('preserves canonical centers, distance and angles through cross-sector repartition and origin/scale changes',()=>{
    const original=copy(),moved=repartition(copy()),a=new PhysicalHierarchy(original),b=new PhysicalHierarchy(moved);
    expect(b.address('a').sector_id).toBe('s2');
    expect(moved.objects).toEqual(original.objects);
    for(const [pair,expected] of Object.entries(fixture.relative)) {
      const [body,origin]=pair.split(':');
      expect(b.relative(body,origin)).toEqual(a.relative(body,origin));
      for(const scale of [1,1e3,1e5,1e9]) {
        const render=renderPosition(b.relative(body,origin),[0,0,0],scale);
        expect(Math.hypot(...render)*scale).toBeCloseTo(Math.hypot(...expected),10);
        const ray=new THREE.Vector3(...render).normalize();
        const expectedRay=new THREE.Vector3(expected[0],expected[2],-expected[1]).normalize();
        expect(ray.distanceTo(expectedRay)).toBeLessThan(1e-14);
      }
    }
    // Preserve small local offsets even where a canonical double loses sub-ULP detail.
    const far=copy();far.hierarchy.sectors[0].origin_km=[1e18,1e18,1e18];
    for(const row of far.objects.filter(row=>row.position)) {
      const body=far.hierarchy.bodies.find(b=>b.id===row.id);
      const system=far.hierarchy.systems.find(s=>s.id===body.system_id);
      const sector=far.hierarchy.sectors.find(s=>s.id===system.sector_id);
      row.position=body.offset_km.map((v,i)=>sector.origin_km[i]+system.offset_km[i]+v);
    }
    const graph=new PhysicalHierarchy(far);
    expect(graph.relative('b','a')).toEqual([.125,.5,1]);
  });
  it('preserves all 100 Horizons reference centers across charts and selected origins',()=>{
    let count=0;
    for(const body of horizons.samples) for(let date=0; date<body.rows.length;date++) {
      const reference=body.rows[date],sun=horizons.samples.find(sample=>sample.id==='sun').rows[date];
      const frame=copy();frame.jd_tdb=reference.jd_tdb;frame.hierarchy.jd_tdb=reference.jd_tdb;
      frame.coordinates.source='JPL Horizons DE441 reference fixture';
      frame.hierarchy.sectors=[{id:'s1',origin_km:[1e8,-2e8,3e7]},{id:'s2',origin_km:[-1e8,2e8,-3e7]}];
      frame.hierarchy.systems=[{id:'sys1',sector_id:'s1',offset_km:[1e3,2e3,-3e3]}, {id:'sys2',sector_id:'s2',offset_km:[-1e3,-2e3,3e3]}];
      frame.objects=[{id:body.id,status:'computed',position:[...reference.position]}];
      if(body.id!=='sun')frame.objects.push({id:'sun',status:'computed',position:[...sun.position]});
      const place=(row,chart)=>({id:row.id,system_id:frame.hierarchy.systems[chart].id,offset_km:row.position.map((v,a)=>v-frame.hierarchy.sectors[chart].origin_km[a]-frame.hierarchy.systems[chart].offset_km[a])});
      frame.hierarchy.bodies=frame.objects.map(row=>place(row,0));
      const first=new PhysicalHierarchy(frame),saved=structuredClone(frame.objects);
      frame.hierarchy.bodies[0]=place(frame.objects[0],1);
      const next=new PhysicalHierarchy(frame);
      expect(frame.objects).toEqual(saved);
      for(const graph of [first,next]) {
        graph.absolute(body.id).forEach((v,a)=>expect(Math.abs(v-reference.position[a])).toBeLessThan(1e-6));
        const relative=graph.relative(body.id,'sun');
        relative.forEach((v,a)=>expect(Math.abs(v-(reference.position[a]-sun.position[a]))).toBeLessThan(1e-6));
      }
      count++;
    }
    expect(count).toBe(100); // 1e-6 km here bounds chart arithmetic only, not source uncertainty.
  });
  it('uses hierarchy during real layer updates and keeps renderer-owned resources through repeated repartition',()=>{
    const scene=new THREE.Scene(),layer=createPhysicalLayer(scene),original=copy(),moved=repartition(copy());
    const geometry=scene.children[0].geometry,material=scene.children[0].material;
    layer.update(original,'a',true);const before=layer.inspect();
    for(let i=0;i<20;i++) {
      layer.update(moved,'a',true);expect(layer.inspect().render).toEqual(before.render);
      expect(layer.inspect().rows).toEqual(before.rows);
      expect(layer.inspect().hierarchy.addresses[0].sector_id).toBe('s2');
      layer.update(null);expect(layer.inspect().rows).toEqual([]);
      layer.update(original,'a',true);expect(layer.inspect()).toEqual(before);
    }
    expect(scene.children[0].geometry).toBe(geometry);expect(scene.children[0].material).toBe(material);
    const dispose=vi.spyOn(geometry,'dispose');layer.dispose();expect(dispose).toHaveBeenCalledOnce();
    expect(original).toEqual(fixture.frame);
  });
  it('rejects stale time/revision, incompatible frames, duplicates, missing parents and corrupt/oversized placements',()=>{
    const cases=[
      f=>f.hierarchy=null,
      ...['version','revision','reference_system','origin','unit','time_scale','evaluated_at','jd_tdb'].map(key=>f=>f.hierarchy[key]='wrong'),
      f=>f.coordinates.time_scale='UTC',f=>f.coordinates.revision='old',f=>delete f.revision,
      f=>f.hierarchy.sectors.push(f.hierarchy.sectors[0]),
      f=>f.hierarchy.systems[0].sector_id='missing',f=>f.hierarchy.bodies[0].system_id='missing',
      f=>f.objects.push(f.objects[0]),f=>f.objects[0].id='missing',f=>f.objects[1]=f.objects[0],
      f=>f.hierarchy.bodies[0].offset_km=[0,0,0],f=>f.hierarchy.bodies[0].offset_km=[NaN,0,0],
      f=>f.hierarchy.sectors[0].origin_km=null,f=>f.hierarchy.bodies[0].offset_km=null,
      f=>f.hierarchy.bodies[0].id='',f=>f.hierarchy.bodies[0].offset_km=[1,2],
      f=>f.hierarchy.bodies.push(f.hierarchy.bodies[0]),f=>f.hierarchy.systems=null,
      f=>f.hierarchy.bodies=Array(4097).fill({}),f=>f.hierarchy.systems=Array(513).fill({}),
      f=>f.hierarchy.sectors=Array(129).fill({}),f=>f.hierarchy.sectors[0].origin_km=[1e308,1e308,1e308],
      f=>f.objects[0].position=[Infinity,0,0], f=>f.hierarchy.bodies[0]=null,
    ];
    for(const mutate of cases) { const frame=copy();mutate(frame);expect(()=>physicalFrame(frame)).toThrow(); }
    const unknown=copy();unknown.hierarchy.bodies[4].offset_km=null;
    expect(verifiedRows(unknown)).toHaveLength(4);
    unknown.hierarchy.bodies[4].system_id=null;
    const unlocated=new PhysicalHierarchy(unknown);
    expect(unlocated.absolute('unknown')).toBe(null);expect(unlocated.address('unknown')).toBe(null);
    unknown.hierarchy.bodies[4].offset_km=[0,0,0];expect(()=>new PhysicalHierarchy(unknown)).toThrow();
    const empty=copy();empty.objects=[];empty.hierarchy.bodies=[];
    expect(physicalFrame(empty).rows).toEqual([]);
  });
});

"""Registry identities and bounded capabilities; synthetic providers are test-only."""
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.position_api import install_position_api
from data.source_registry import REGISTRY, MODEL, SourceRegistry
from data.ephemeris import Ephemeris, contract, REVISION


def synthetic(count=6):
    model = dict(MODEL, id='synthetic-test', provider='synthetic', model='synthetic',
                 source='synthetic test data; not NASA', revision='test-1', solver='synthetic-test', source_url='https://example.invalid/synthetic', asset='test-only', sha256='0'*64, provider_revision='test-only', identity_namespace='synthetic-test', axes='synthetic test XYZ')
    return SourceRegistry([model], [dict(id=f'synthetic-{i}', target=10000+i,
        identity_type='body_center', model_id=model['id'], name=f'Synthetic {i}',
        kind='planet', color='#ffffff') for i in range(count)])


class RegistryTests(unittest.TestCase):
    def test_validation_identity_and_immutability(self):
        rows=REGISTRY.page()['objects']
        mutations=[lambda m,r:r.append(r[0]),
            lambda m,r:r.append(dict(r[0],id='alias')),
            lambda m,r:r[0].update(identity_type='ambiguous'),
            lambda m,r:r[0].update(model_id='missing'),
            lambda m,r:r[0].update(color='red'),
            lambda m,r:r[0].update(target=True),
            lambda m,r:r[0].update(target=3),
            lambda m,r:r[0].update(id=None),
            lambda m,r:r[0].update(extra='bad'),
            lambda m,r:m[0].update(extra='bad'),
            lambda m,r:m[0].update(source=123),
            lambda m,r:m[0].update(utc_interval='bad'),
            lambda m,r:m[0].update(utc_interval=['bad','bad']),
            lambda m,r:m[0].update(utc_interval=['2000-01-01','2027-01-01']),
            lambda m,r:m[0].update(tdb_jd_interval=['bad','bad']),
            lambda m,r:r[0].update(id=''),
            lambda m,r:r[0].update(name='x'*2000),
            lambda m,r:m[0].update(sha256='bad'),
            lambda m,r:m[0].update(accuracy=0),
            lambda m,r:m[0].update(utc_interval=['2027-01-01T00:00:00Z','2000-01-01T00:00:00Z']),
            lambda m,r:m[0].update(interval_end='inclusive'),
            lambda m,r:m.append(m[0]),
            lambda m,r:m[0].update(source=''),
            lambda m,r:m[0].update(source_url='x'*9000)]
        for mutate in mutations:
            m,r=deepcopy([MODEL]),deepcopy(rows);mutate(m,r)
            with self.subTest(mutate=mutate),self.assertRaises(ValueError):SourceRegistry(m,r)
        with self.assertRaises(ValueError):SourceRegistry([MODEL]*129,[])
        class Excessive(list):
            def __len__(self):return 1000001
        with self.assertRaises(ValueError):SourceRegistry([MODEL],Excessive())
        rows[0]['name']='changed'
        self.assertEqual(REGISTRY.object('sun')['name'],'Солнце')
        with self.assertRaises(TypeError):REGISTRY.targets['extra']=1
        # A barycenter is distinct from its center, never silently aliased.
        r=REGISTRY.page()['objects'];r.append(dict(r[0],id='solar_barycenter',target=0,identity_type='barycenter'))
        self.assertEqual(SourceRegistry([MODEL],r).object('solar_barycenter')['target'],0)
        self.assertIsNone(REGISTRY.object('mars'))

    def test_pages_revisions_and_limits(self):
        registry=synthetic(300)
        first=registry.page(limit=128);second=registry.page(128,128);last=registry.page(256,128)
        self.assertEqual([len(p['objects']) for p in [first,second,last]],[128,128,44])
        self.assertIsNone(last['next_offset'])
        self.assertEqual(len({r['id'] for p in [first,second,last] for r in p['objects']}),300)
        self.assertEqual(registry.page(q='Synthetic 299')['objects'][0]['id'],'synthetic-299')
        for args in [(-1,1),(0,129),(0,0),(1000001,1)]:
            with self.assertRaises(ValueError):registry.page(*args)
        for field,value in [('revision','new'),('sha256','a'*64),('provider_revision','new')]:
            model=dict(MODEL,**{field:value})
            self.assertNotEqual(SourceRegistry([model],REGISTRY.page()['objects']).revision,REGISTRY.revision)
        self.assertNotEqual(synthetic(5).revision,synthetic(6).revision)
        self.assertEqual(contract(SourceRegistry([MODEL],REGISTRY.page()['objects']))['revision'],REVISION)

    def client(self, registry=REGISTRY, engine_factory=None):
        app=FastAPI();install_position_api(app,lambda supplied,etag:supplied in ('*',etag),registry,engine_factory)
        return TestClient(app)

    def test_http_paging_etag_conflict_and_limits(self):
        with self.client(synthetic(300)) as client:
            url='/api/sources/v1/objects?limit=2'
            response=client.get(url);self.assertEqual(response.status_code,200)
            self.assertLess(len(response.content),256*1024)
            self.assertEqual(len(response.json()['objects']),2)
            self.assertEqual(client.get(url,headers={'If-None-Match':response.headers['etag']}).status_code,304)
            self.assertEqual(client.get(url+'&revision=old',headers={'If-None-Match':'*'}).status_code,409)
            for query in ['limit=0','limit=129','offset=-1','offset=1000001','q='+'x'*129,'revision='+'x'*65]:
                self.assertEqual(client.get('/api/sources/v1/objects?'+query,headers={'If-None-Match':'*'}).status_code,422)
            self.assertEqual(client.get('/api/sources/v1/objects?offset=300').json()['objects'],[])
        with self.client() as client:
            response_contract=client.get('/api/positions/v1/contract')
            self.assertEqual(client.get('/api/positions/v1/contract',headers={'If-None-Match':response_contract.headers['etag']}).status_code,304)
        with self.client(synthetic(301)) as client:
            self.assertNotEqual(client.get(url).headers['etag'],response.headers['etag'])
        with self.client() as client,patch.object(type(REGISTRY),'page',return_value={'oversized':'x'*(256*1024)}):
            self.assertEqual(client.get('/api/sources/v1/objects',headers={'If-None-Match':'*'}).status_code,413)

    def test_synthetic_provider_extends_membership_without_solver_edits(self):
        # Deliberately fake provider, with no real/NASA vectors or extra BSP.
        class Kernel:
            def __getitem__(self,target):
                return SimpleNamespace(at=lambda t:SimpleNamespace(position=SimpleNamespace(km=SimpleNamespace(tolist=lambda:[float(target),2.,3.]))))
            def close(self):pass
        provider=SimpleNamespace(kernel=Kernel(),timescale=SimpleNamespace(tdb_jd=lambda jd:SimpleNamespace(tdb=jd)))
        registry=synthetic(9)
        engine=Ephemeris(registry=registry,provider=provider)
        result=engine.evaluate(jd_tdb=2451545)
        self.assertEqual(len(result['objects']),9)
        self.assertEqual(result['objects'][-1]['position'],[10008.,2.,3.])
        self.assertIn('synthetic',result['coordinates']['source'])
        with self.client(registry,lambda:engine) as client:
            url='/api/positions/v1/sectors/solar:verified?jd_tdb=2451545'
            response=client.get(url);self.assertEqual(len(response.json()['objects']),9)
        for count in [10,129]:
            other=synthetic(count);other_engine=Ephemeris(registry=other,provider=provider)
            with self.client(other,lambda:other_engine) as client:
                updated=client.get(url)
                if count==129:self.assertEqual(updated.status_code,413)
                else:self.assertNotEqual(updated.headers['etag'],response.headers['etag'])
        with self.assertRaisesRegex(ValueError,'asset mismatch'):
            Ephemeris(registry=SourceRegistry([dict(MODEL,sha256='a'*64)],REGISTRY.page()['objects']))

    def test_incompatible_models_and_oversized_position_payload_fail_explicitly(self):
        model=dict(MODEL,id='different-frame',reference_system='unconfirmed')
        rows=REGISTRY.page()['objects'];rows[0]['model_id']=model['id']
        with self.assertRaisesRegex(ValueError,'incompatible models'):
            Ephemeris(registry=SourceRegistry([MODEL,model],rows))
        class Oversized:
            def evaluate(self,**kwargs):return {'oversized':'x'*(256*1024)}
            def close(self):pass
        with self.client(engine_factory=Oversized) as client:
            self.assertEqual(client.get('/api/positions/v1/sectors/solar:verified?jd_tdb=2451545',headers={'If-None-Match':'*'}).status_code,413)

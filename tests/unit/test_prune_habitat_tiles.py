"""prune_habitat_tiles checks every manifest before any delete; bad input is a named refusal (RF0140-12)."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest

from tests._support import ROOT

spec=importlib.util.spec_from_file_location('prune_habitat_tiles',ROOT/'scripts/prune_habitat_tiles.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

def tile(n):return f'sst-analysis--242-70-{n:016x}.json'

def manifest(ident,n):
    return {'schema_version':1,'region_id':ident,'layers':{'sst-analysis':{'tiles':[{'path':'habitat-tiles/'+tile(n)}]}}}

class PruneTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        self.root=Path(folder.name);self.published=self.root/'published';self.incoming=self.root/'incoming'
        for ident,base in [('alpha-bay',0),('beta-bay',10)]:
            for where,n in [(self.published,base+1),(self.incoming,base+2)]:
                self.write(where/'regions'/ident/'habitat-dynamics.json',manifest(ident,n))
            tiles=self.published/'regions'/ident/'habitat-tiles';tiles.mkdir()
            for k in range(3):(tiles/tile(base+k)).write_text('{}')

    def write(self,path,data):
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(data if isinstance(data,str) else json.dumps(data))

    def names(self,ident):
        return {p.name for p in (self.published/'regions'/ident/'habitat-tiles').iterdir()}

    def assert_untouched(self):
        self.assertEqual(self.names('alpha-bay'),{tile(0),tile(1),tile(2)})
        self.assertEqual(self.names('beta-bay'),{tile(10),tile(11),tile(12)})

    def refused(self,message):
        with self.assertRaises(ValueError) as caught:module.prune(self.published,self.incoming)
        self.assertEqual(str(caught.exception),message)
        self.assert_untouched()

    def test_unreadable_later_region_leaves_earlier_region_unpruned(self):
        self.write(self.incoming/'regions/beta-bay/habitat-dynamics.json','not json {')
        self.refused('Habitat manifest unreadable: beta-bay')

    def test_misshaped_manifest_is_named_and_nothing_removed(self):
        bad={'no layers':{'schema_version':1,'region_id':'beta-bay'},
             'tiles a dict':{'schema_version':1,'region_id':'beta-bay','layers':{'sst-analysis':{'tiles':{}}}},
             'path an int':{'schema_version':1,'region_id':'beta-bay','layers':{'sst-analysis':{'tiles':[{'path':3}]}}},
             'layer not a dict':{'schema_version':1,'region_id':'beta-bay','layers':{'sst-analysis':[]}},
             'not an object':[1,2]}
        for label,data in bad.items():
            with self.subTest(label):
                self.write(self.incoming/'regions/beta-bay/habitat-dynamics.json',data)
                self.refused('Habitat manifest misshaped: beta-bay')

    def test_unreadable_published_manifest_is_refused(self):
        (self.published/'regions/beta-bay/habitat-dynamics.json').write_bytes(b'\xff\xfe not utf-8')
        self.refused('Habitat manifest unreadable: beta-bay')

    def test_identity_message_names_region(self):
        self.write(self.incoming/'regions/beta-bay/habitat-dynamics.json',manifest('alpha-bay',12))
        self.refused('Habitat identity mismatch: beta-bay')

    def test_linked_tile_folder_is_refused_and_link_target_untouched(self):
        elsewhere=self.root/'elsewhere';elsewhere.mkdir()
        for k in range(20,23):(elsewhere/tile(k)).write_text('{}')
        tiles=self.published/'regions/beta-bay/habitat-tiles'
        for p in tiles.iterdir():p.rename(self.root/p.name)
        tiles.rmdir();tiles.symlink_to(elsewhere,target_is_directory=True)
        with self.assertRaises(ValueError) as caught:module.prune(self.published,self.incoming)
        self.assertEqual(str(caught.exception),'Habitat tile folder is a link: beta-bay')
        self.assertEqual({p.name for p in elsewhere.iterdir()},{tile(20),tile(21),tile(22)})
        self.assertEqual(self.names('alpha-bay'),{tile(0),tile(1),tile(2)})

    def test_good_two_regions_remove_stale_tiles_only(self):
        tiles=self.published/'regions/alpha-bay/habitat-tiles'
        (tiles/'user-notes.json').write_text('{}');os.symlink(self.root/'x.json',tiles/tile(5))
        self.assertEqual(module.prune(self.published,self.incoming),2)
        self.assertEqual(self.names('alpha-bay'),{tile(1),tile(2),'user-notes.json',tile(5)})
        self.assertEqual(self.names('beta-bay'),{tile(11),tile(12)})

    def test_cli_refusal_and_success(self):
        argv=[str(self.published),str(self.incoming)]
        self.write(self.incoming/'regions/beta-bay/habitat-dynamics.json','[')
        out,err=io.StringIO(),io.StringIO()
        with contextlib.redirect_stdout(out),contextlib.redirect_stderr(err):code=module.main(argv)
        self.assertEqual((code,out.getvalue(),err.getvalue()),(1,'','prune_habitat_tiles: Habitat manifest unreadable: beta-bay\n'))
        self.assert_untouched()
        self.write(self.incoming/'regions/beta-bay/habitat-dynamics.json',manifest('beta-bay',12))
        out=io.StringIO()
        with contextlib.redirect_stdout(out):code=module.main(argv)
        self.assertEqual((code,out.getvalue()),(0,'Removed 2 unreferenced old habitat tiles\n'))

if __name__=='__main__':unittest.main()

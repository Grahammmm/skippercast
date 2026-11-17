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

    def link_region(self,dest):
        """Move published beta-bay to `dest` and leave a link to dest in its place."""
        region=self.published/'regions/beta-bay'
        if dest.exists() or dest.is_symlink():raise AssertionError('destination must not exist')
        region.rename(dest);region.symlink_to(dest,target_is_directory=True)

    def link_regions(self,dest,dangling=False):
        regions=self.published/'regions';regions.rename(self.root/'moved')
        if not dangling:(self.root/'moved').rename(dest)
        regions.symlink_to(dest,target_is_directory=True)

    def files(self,base):return sorted(str(p.relative_to(base)) for p in base.rglob('*') if p.is_file())

    def refused_link(self,message,*dirs):
        before=[self.files(d) for d in dirs]
        with self.assertRaises(ValueError) as caught:module.prune(self.published,self.incoming)
        self.assertEqual(str(caught.exception),message)
        self.assertEqual([self.files(d) for d in dirs],before)

    def test_linked_region_ancestor_refuses_before_any_delete(self):
        dest=self.root/'outside';self.link_region(dest)
        self.refused_link('Habitat region folder is a link: beta-bay',dest,self.published/'regions/alpha-bay')
        self.assertEqual(self.names('alpha-bay'),{tile(0),tile(1),tile(2)})
        self.assertEqual({p.name for p in (dest/'habitat-tiles').iterdir()},{tile(10),tile(11),tile(12)})

    def test_linked_regions_ancestor_refuses_before_any_delete(self):
        dest=self.root/'outside';self.link_regions(dest)
        self.refused_link('Habitat regions folder is a link',dest)
        self.assertEqual(len(self.files(dest)),8)

    def test_dangling_published_ancestor_links_are_refused(self):
        with self.subTest('regions'):
            self.link_regions(self.root/'missing',dangling=True)
            self.refused_link('Habitat regions folder is a link')
        self.setUp()
        with self.subTest('beta-bay'):
            self.link_region(self.root/'moved-away');(self.root/'moved-away').rename(self.root/'gone')
            self.refused_link('Habitat region folder is a link: beta-bay',self.published/'regions/alpha-bay')
            self.assertEqual(self.names('alpha-bay'),{tile(0),tile(1),tile(2)})

    def test_in_root_region_symlink_is_refused(self):
        dest=self.published/'other-place';self.link_region(dest)
        self.refused_link('Habitat region folder is a link: beta-bay',dest,self.published/'regions/alpha-bay')
        self.assertEqual({p.name for p in (dest/'habitat-tiles').iterdir()},{tile(10),tile(11),tile(12)})

    def test_cli_linked_ancestor_refusal(self):
        for label in ('regions','beta-bay'):
            with self.subTest(label):
                self.setUp();dest=self.root/'outside';argv=[str(self.published),str(self.incoming)]
                if label=='regions':self.link_regions(dest);message='Habitat regions folder is a link'
                else:self.link_region(dest);message='Habitat region folder is a link: beta-bay'
                before=self.files(dest)
                out,err=io.StringIO(),io.StringIO()
                with contextlib.redirect_stdout(out),contextlib.redirect_stderr(err):code=module.main(argv)
                self.assertEqual((code,out.getvalue(),err.getvalue()),(1,'',f'prune_habitat_tiles: {message}\n'))
                self.assertEqual(self.files(dest),before)

    def test_missing_nonlink_published_folders_remain_harmless(self):
        regions=self.published/'regions';regions.rename(self.root/'moved')
        self.assertEqual(module.prune(self.published,self.incoming),0)
        self.assertFalse(regions.exists())
        regions.mkdir()
        self.assertEqual(module.prune(self.published,self.incoming),0)
        self.assertEqual(list(regions.iterdir()),[])

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

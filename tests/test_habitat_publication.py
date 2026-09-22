import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('prune_habitat_tiles',Path(__file__).parents[1]/'scripts/prune_habitat_tiles.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

class Publication(unittest.TestCase):
    def test_retains_outgoing_and_incoming_generations_and_unowned_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);published=root/'published';incoming=root/'incoming'
            files=[f'sst-analysis--242-70-{n:016x}.json' for n in range(3)]
            dest=published/'regions/morro-bay/habitat-tiles';dest.mkdir(parents=True)
            for name in files+['user-notes.json']:(dest/name).write_text('{}')
            for base,i in [(published,1),(incoming,2)]:
                target=base/'regions/morro-bay';target.mkdir(parents=True,exist_ok=True)
                (target/'habitat-dynamics.json').write_text(json.dumps({'schema_version':1,'region_id':'morro-bay','layers':{'sst-analysis':{'tiles':[{'path':'habitat-tiles/'+files[i]}]}}}))
            self.assertEqual(module.prune(published,incoming),1)
            self.assertEqual({p.name for p in dest.iterdir()},{files[1],files[2],'user-notes.json'})

if __name__=='__main__':unittest.main()

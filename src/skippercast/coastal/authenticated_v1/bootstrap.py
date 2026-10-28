"""Fixed absolute bootstrap: isolated Python ignores artifact-root import shadows."""
import os,sys
from pathlib import Path
if not sys.flags.isolated:raise SystemExit('isolated interpreter required')
# Works from src checkout or installed package; the runner binds this exact file.
sys.dont_write_bytecode=True
for name,value in dict(PROJ_NETWORK="OFF",GDAL_PAM_ENABLED="NO",GDAL_DRIVER_PATH="disable",GDAL_NUM_THREADS="2",OMP_NUM_THREADS="2",OPENBLAS_NUM_THREADS="2",MKL_NUM_THREADS="2").items():os.environ[name]=value
package_root=Path(os.path.abspath(__file__)).parents[2]
guard_source=package_root/'coastal'/'_source_bootstrap.py'
guard_namespace={'__name__':'_verified_project_source_guard','__file__':str(guard_source)}
exec(compile(guard_source.read_bytes(),str(guard_source),'exec'),guard_namespace)
guard_namespace['guard_project_source'](package_root)
sys.path.insert(0,str(package_root.parent))
from skippercast.coastal.authenticated_v1.worker import main
if __name__=='__main__':raise SystemExit(main())

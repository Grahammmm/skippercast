"""Newly generated synthetic BAG only; never imports dated prototype outputs."""
import hashlib
import numpy as np,h5py,rasterio
from rasterio.shutil import copy as raster_copy
from rasterio.transform import from_origin
def make_bag(root, *, side=32, seed=None):
    bag=root/'H11879_MB_2m_MLLW_1of5.bag';tif=root/'synthetic-values.tif'
    a=np.full((side,side),-20.,dtype='float32');u=np.full((side,side),.25,dtype='float32')
    if seed is not None:
        rng=np.random.default_rng(seed)
        a=-rng.uniform(1,90,size=(side,side)).astype('float32')
        u=rng.uniform(.01,.99,size=(side,side)).astype('float32')
    a[0,:8]=[-7,-7.62,-10,-91.44,-92,0,20,-9999];u[0,5]=0;u[0,7]=-9999
    u[1,:4]=[0,-1,1.01,2]
    with rasterio.Env(GDAL_PAM_ENABLED='NO',GDAL_NUM_THREADS='2',PROJ_NETWORK='OFF'):
        with rasterio.open(tif,'w',driver='GTiff',width=side,height=side,count=2,dtype='float32',crs='EPSG:26911',transform=from_origin(432000,3702000,2,2),nodata=-9999) as f:f.write(a,1);f.write(u,2)
        raster_copy(tif,bag,driver='BAG')
    vc='VERT_CS["MLLW depth", VERT_DATUM["Mean Lower Low Water",2005, AUTHORITY["EPSG","1089"]], UNIT["metre",1,AUTHORITY["EPSG","9001"]],AXIS["Depth",DOWN]]'
    with h5py.File(bag,'r+') as f:
        root=f['BAG_root'];xml=root['metadata'][:].tobytes().decode().rstrip('\0')
        xml=xml.replace('VERT_CS["unknown", VERT_DATUM["unknown", 2000]]',vc)
        xml=xml.replace('<gco:CharacterString>unknown</gco:CharacterString>','<gco:CharacterString>H11879 TEST ONLY SYNTHETIC metadata</gco:CharacterString>',1)
        xml=xml.replace('codeListValue="unknown">unknown</bag:BAG_VertUncertCode>','codeListValue="productUncert">productUncert</bag:BAG_VertUncertCode>')
        xml=xml.replace('</gmi:MI_Metadata>','<gml:beginPosition>2020-01-01</gml:beginPosition><gml:endPosition>2020-01-02</gml:endPosition></gmi:MI_Metadata>')
        del root['metadata'];root.create_dataset('metadata',data=np.frombuffer(xml.encode(),dtype='S1'),maxshape=(None,),chunks=True)
    contents=bag.read_bytes();sha=hashlib.sha256(contents).hexdigest()
    row=dict(id='TEST_ONLY_SYNTHETIC_SOURCE',title=bag.name,url='https://data.ngdc.noaa.gov/platforms/ocean/nos/coast/H11879/BAG/'+bag.name,format='bag',kind='bathymetry',sha256=sha,horizontal_crs='EPSG:26911',vertical_datum='MLLW',resolution_m=2)
    return bag,row,hashlib.sha256(xml.encode()).hexdigest(),len(contents)



def run_unguarded_poison_control(package_parent, root):
    """Actual isolated subprocess control, intentionally bypassing the source guard.

    The absolute generated package path is needed solely to demonstrate that
    disabling bytecode writes does not stop timestamp-valid bytecode reads.
    This fixture helper never selects product/native source paths.
    """
    import subprocess,sys
    return subprocess.run([sys.executable, "-I", "-B", "-c",
        "import sys;sys.path.insert(0," + repr(str(package_parent)) + ");import skippercast"],
        cwd=root, capture_output=True, text=True, timeout=10)

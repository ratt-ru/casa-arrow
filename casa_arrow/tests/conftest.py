import multiprocessing as mp
import os
from pathlib import Path
from hashlib import sha256

import requests
import tarfile
import pytest

TAU_MS = "HLTau_B6cont.calavg.tav300s"
TAU_MS_TAR = f"{TAU_MS}.tar.xz"
TAU_MS_TAR_HASH = "fc2ce9261817dfd88bbdd244c8e9e58ae0362173938df6ef2a587b1823147f70"
DATA_URL = f"https://ratt-public-data.s3.af-south-1.amazonaws.com/test-data/{TAU_MS_TAR}"
DATA_CHUNK_SIZE = 2**20

def download_tau_ms(tau_ms_tar):
    if tau_ms_tar.exists():
        with open(tau_ms_tar, "rb") as f:
            digest = sha256()

            while data := f.read(DATA_CHUNK_SIZE):
                digest.update(data)

            if digest.hexdigest() == TAU_MS_TAR_HASH:
                return

            tau_ms_tar.unlink(missing_ok=True)
            raise ValueError(
                f"SHA256 digest mismatch for {tau_ms_tar}. "
                f"{digest.hexdigest()} != {TAU_MS_TAR_HASH}")
    else:
        response = requests.get(DATA_URL, stream=True)

        with open(tau_ms_tar, "wb") as fout:
            digest = sha256()

            for data in response.iter_content(chunk_size=DATA_CHUNK_SIZE):
                digest.update(data)
                fout.write(data)

            if digest.hexdigest() != TAU_MS_TAR_HASH:
                raise ValueError(
                    f"SHA256 digest mismatch for {DATA_URL}. "
                    f"{digest.hexdigest()} != {TAU_MS_TAR_HASH}")

@pytest.fixture(scope="session")
def tau_ms_tar():
    from appdirs import user_cache_dir
    cache_dir = Path(user_cache_dir("casa-arrow")) / "test-data"
    cache_dir.mkdir(parents=True, exist_ok=True)
    tau_ms_tar = cache_dir / TAU_MS_TAR

    download_tau_ms(tau_ms_tar)
    return tau_ms_tar


@pytest.fixture(scope="session")
def tau_ms(tau_ms_tar, tmp_path_factory):
    msdir = tmp_path_factory.mktemp("tau-ms")

    with tarfile.open(tau_ms_tar) as tar:
        tar.extractall(msdir)

    return str(msdir / TAU_MS)


@pytest.fixture(scope="session")
def partitioned_dataset(tau_ms, tmp_path_factory):
    import casa_arrow as ca
    import pyarrow as pa
    import pyarrow.dataset as pad

    dsdir = tmp_path_factory.mktemp("partition-dataset")

    AT = ca.table(tau_ms).to_arrow()
    partition_fields = [AT.schema.field(c) for c in ("FIELD_ID", "DATA_DESC_ID")]
    partition = pad.partitioning(pa.schema(partition_fields), flavor="hive")
    pad.write_dataset(AT, dsdir, partitioning=partition,
                      max_rows_per_group=25000,
                      max_rows_per_file=25000,
                      format="parquet")

    return dsdir


def generate_column_cases_table(path):
    import pyrap.tables as pt
    import numpy as np
    nrow = 3

    # Table descriptor
    table_desc = [
        {
            "desc": {
                "_c_order": True,
                "comment": "VARIABLE column",
                "dataManagerGroup": "",
                "dataManagerType": "",
                "keywords": {},
                "ndim": 3,
                "maxlen": 0,
                "option": 0,
                "valueType": "int",
            },
            "name": "VARIABLE",
        },
        {
            "desc": {
                "_c_order": True,
                "comment": "VARIABLE_STRING column",
                "dataManagerGroup": "",
                "dataManagerType": "",
                "keywords": {},
                "ndim": 3,
                "maxlen": 0,
                "option": 0,
                "valueType": "string",
            },
            "name": "VARIABLE_STRING",
        },
        {
            "desc": {
                "_c_order": True,
                "comment": "FIXED column",
                "dataManagerGroup": "",
                "dataManagerType": "",
                "keywords": {},
                "ndim": 2,
                "shape": [2, 4],
                "maxlen": 0,
                "option": 0,
                "valueType": "int",
            },
            "name": "FIXED",
        },
        {
            "desc": {
                "_c_order": True,
                "comment": "FIXED_STRING column",
                "dataManagerGroup": "",
                "dataManagerType": "",
                "keywords": {},
                "ndim": 2,
                "shape": [2, 4],
                "maxlen": 0,
                "option": 0,
                "valueType": "string",
            },
            "name": "FIXED_STRING",
        },
        {
            "desc": {
                "_c_order": True,
                "comment": "SCALAR column",
                "dataManagerGroup": "",
                "dataManagerType": "",
                "keywords": {},
                "maxlen": 0,
                "option": 0,
                "valueType": "int",
            },
            "name": "SCALAR",
        },
        {
            "desc": {
                "_c_order": True,
                "comment": "SCALAR_STRING column",
                "dataManagerGroup": "",
                "dataManagerType": "",
                "keywords": {},
                "maxlen": 0,
                "option": 0,
                "valueType": "string",
            },
            "name": "SCALAR_STRING",
        },
        {
            "desc": {
                "_c_order": True,
                "comment": "UNCONSTRAINED column",
                "dataManagerGroup": "",
                "dataManagerType": "",
                "keywords": {},
                "maxlen": 0,
                "ndim": -1,
                "option": 0,
                "valueType": "int",
            },
            "name": "UNCONSTRAINED",
        }

    ]

    table_desc = pt.maketabdesc(table_desc)
    table_name = os.path.join(path, "test.table")

    with pt.table(table_name, table_desc, nrow=nrow, ack=False) as T:
        for i in range(nrow):
            T.putcell("VARIABLE", i, np.full((3, 1 + i, 2), i))
            T.putcell("FIXED", i, np.full((2, 4), i))
            T.putcell("SCALAR", i, i)

            T.putcell("VARIABLE_STRING", i, np.full((3, 1 + i, 2), str(i)))
            T.putcell("FIXED_STRING", i, np.full((2, 4), str(i)))
            T.putcell("SCALAR_STRING", i, str(i))

        T.putcell("UNCONSTRAINED", 0, np.full((2, 3, 4), 0))
        T.putcell("UNCONSTRAINED", 1, np.full((4, 3), 1))
        T.putcell("UNCONSTRAINED", 1, 1)

    return table_name


@pytest.fixture
def column_case_table(tmp_path_factory):
    # Generate casa table in a spawned process, otherwise
    # the pyrap.tables casacore libraries will be loaded in
    # and interfere with system casacore libraries
    path = tmp_path_factory.mktemp("column_cases")

    with mp.get_context("spawn").Pool(1) as pool:
        result = pool.apply_async(generate_column_cases_table, (str(path),))
        return result.get()

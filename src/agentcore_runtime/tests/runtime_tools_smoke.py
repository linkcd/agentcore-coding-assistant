"""Exercise installed tools and native extensions without network or model calls."""

import json
import os
import shlex
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path


def execute(*args, **kwargs):
    try:
        return subprocess.check_output(
            args, text=True, stderr=subprocess.STDOUT, timeout=90, **kwargs
        )
    except subprocess.CalledProcessError as exc:
        print(exc.output, flush=True)
        raise


def main():
    assert os.getuid() == 1000, "Tool checks must run as the agent user"
    versions = {}
    for name in (
        "python",
        "python3",
        "python3.13",
        "pip",
        "pip3",
        "node",
        "npm",
        "npx",
        "uv",
        "uvx",
        "pnpm",
        "cargo",
        "rustc",
        "rustfmt",
        "cargo-clippy",
        "gh",
        "aws",
        "rg",
    ):
        assert shutil.which(name), name
        versions[name] = execute(name, "--version").splitlines()[0]
    versions["go"] = execute("go", "version").strip()
    store = Path(execute("pnpm", "store", "path").strip())
    assert store.is_relative_to(Path(os.environ["PNPM_CONFIG_STORE_DIR"])), store
    assert execute("npm", "config", "get", "cache").strip() == os.environ["npm_config_cache"]
    for name in (
        "git",
        "ssh",
        "curl",
        "wget",
        "gcc",
        "g++",
        "make",
        "cmake",
        "ninja",
        "pkg-config",
        "jq",
        "file",
        "tree",
        "sqlite3",
        "patch",
        "diff",
        "rsync",
        "less",
        "nano",
        "ip",
        "dig",
        "tar",
        "gzip",
        "unzip",
        "zip",
        "xz",
        "bzip2",
    ):
        assert shutil.which(name), name
    with tempfile.TemporaryDirectory(prefix="tool-smoke-") as directory:
        root = Path(directory)
        source = root / "extension.c"
        source.write_text(
            "#include <Python.h>\n"
            'static struct PyModuleDef m={PyModuleDef_HEAD_INIT,"probe",0,-1,0};\n'
            "PyMODINIT_FUNC PyInit_probe(void){return PyModule_Create(&m);}\n"
        )
        for python in ("python3", "python3.13"):
            info = json.loads(
                execute(
                    python,
                    "-c",
                    "import json,sysconfig; print(json.dumps([sysconfig.get_path('include'),"
                    "sysconfig.get_config_var('EXT_SUFFIX')]))",
                )
            )
            output = root / ("probe" + info[1])
            execute("gcc", "-shared", "-fPIC", "-I" + info[0], str(source), "-o", str(output))
            execute(
                python,
                "-c",
                "import probe,ssl,sqlite3,ctypes,bz2,lzma,zlib,readline,venv",
                cwd=root,
            )
        cpp = root / "hello.cpp"
        cpp.write_text('#include <iostream>\nint main(){std::cout << "CXX_OK";}\n')
        execute("g++", str(cpp), "-o", str(root / "cpp"))
        assert execute(str(root / "cpp")) == "CXX_OK"
        c = root / "crypto.c"
        c.write_text("#include <openssl/crypto.h>\nint main(){return OpenSSL_version_num()==0;}\n")
        flags = shlex.split(execute("pkg-config", "--cflags", "--libs", "openssl"))
        execute("gcc", str(c), "-o", str(root / "crypto"), *flags)
        execute(str(root / "crypto"))
        js = root / "addon.c"
        js.write_text(
            "#include <node_api.h>\nnapi_value init(napi_env e,napi_value exports){"
            "napi_value v; napi_create_int32(e,42,&v); "
            'napi_set_named_property(e,exports,"answer",v); return exports;}\n'
            "NAPI_MODULE(probe,init)\n"
        )
        execute(
            "gcc",
            "-shared",
            "-fPIC",
            "-I/usr/local/include/node",
            str(js),
            "-o",
            str(root / "addon.node"),
        )
        execute(
            "node",
            "-e",
            "if(require(process.argv[1]).answer!==42)process.exit(1)",
            str(root / "addon.node"),
        )
        go = root / "hello.go"
        go.write_text('package main\nimport "fmt"\nfunc main(){fmt.Print("GO_OK")}\n')
        assert execute("go", "run", str(go), cwd=root) == "GO_OK"
        rust = root / "hello.rs"
        rust.write_text('fn main(){print!("RUST_OK");}\n')
        execute("rustc", str(rust), "-o", str(root / "rust"))
        assert execute(str(root / "rust")) == "RUST_OK"
        execute("uv", "venv", "--offline", "--python", "python3.13", str(root / "venv"))
        execute(str(root / "venv/bin/python"), "-c", "import ssl,sqlite3")
        # Install a unique local CLI, invoke it through PATH, then remove only this fixture.
        name = "agentcore-tool-probe-" + uuid.uuid4().hex
        package = root / "npm-package"
        package.mkdir()
        (package / "package.json").write_text(
            json.dumps({"name": name, "version": "1.0.0", "bin": {name: "cli.js"}})
        )
        (package / "cli.js").write_text('#!/usr/bin/env node\nconsole.log("NPM_INSTALL_OK")\n')
        try:
            execute(
                "npm",
                "install",
                "--global",
                "--offline",
                "--ignore-scripts",
                "--no-audit",
                "--no-fund",
                str(package),
            )
            assert execute(name).strip() == "NPM_INSTALL_OK"
        finally:
            execute(
                "npm",
                "uninstall",
                "--global",
                "--offline",
                "--ignore-scripts",
                "--no-audit",
                "--no-fund",
                name,
            )
    print(json.dumps({"versions": versions, "native_builds": "passed", "local_installs": "passed"}))


if __name__ == "__main__":
    main()

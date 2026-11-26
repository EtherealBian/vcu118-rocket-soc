# Third-party sources and redistribution

The pinned build sources are not relicensed by this project. Chipyard is the integration tree; consult its `LICENSE`, `LICENSE.SiFive` and the license/notice files in every used submodule rather than assuming one license covers the FPGA image. Chipyard commit: `69eba860a352343e4ac6b6df0f3638a79a86ec78`. Rocket Chip: `72690b07c0939a58670418b97e5442835b2049b5`. FPGA Shells: `2d36b0ab430fe3dc4cf378f378be21b925379110`.

Software source locators are in `scripts/fetch-image-sources.sh`, exact archive digests in `sources.sha256`. In the extracted trees preserve Linux `COPYING` and `LICENSES/`, BusyBox `LICENSE` and file-level notices, OpenSBI `COPYING*` and file-level notices. The statically linked toolchain libraries (including musl and compiler runtime) have additional terms. The cross SDK is identified in `scripts/fetch-cross.sh`. Preserve binaries, matching source, build scripts, config and notices together when preparing a distribution. This repository is a working engineering delivery, not a complete redistribution compliance bundle.

Firmware and freeware development tools are distinct: AMD Vivado/Vitis, board files and generated AMD IP are provided under their own terms. The build expects a local authorized installation and does not redistribute that installation. QEMU, GNU Make, JDK, jq, CIRCT and sbt also retain their upstream terms; their locations are given by the fetch scripts, Ubuntu package metadata or Chipyard's project files.

The optional benchmark is fetched from `eembc/coremark` at `9d07b05523c16754a214a40224018a4ee908e091`. Its source files carry Apache-2.0 notices; see also the upstream `LICENSE.md` acceptable-use/trademark terms and `README.md` reporting rules. CoreMark® is a registered trademark of the Embedded Microprocessor Benchmark Consortium. This repository contains our build and measurement scripts, not the benchmark sources or binary. Results are independent engineering measurements, not a certification or an endorsement.

The optional packed loader uses the host system’s LZ4 library (BSD-2-Clause library code) for block compression and a host round trip. The target uses the small project decoder in `software/boot-pack`; neither an upstream LZ4 library binary nor its source is distributed in this repository.


BOOM v3 is used at Chipyard submodule `d2a64f7ca9fd914d9c686cb23edcd32d3465a02e`; keep its original notices when rebuilding. The optional GCC 15.1 SDK is independently hash-pinned by `scripts/fetch-cpu-cross.sh`. Neither the SDK nor third-party RTL/binaries are redistributed here.

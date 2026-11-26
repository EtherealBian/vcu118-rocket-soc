#!/usr/bin/env bash
set -u
for t in cmake verilator java dtc curl python3 gcc make qemu-riscv64 unzip bzip2 sgdisk lz4 flex bison cpio fakeroot; do command -v "$t" || :; done
cat /etc/os-release | head -4
getconf GNU_LIBC_VERSION
ls ~/tools ~/work
apt-cache policy gcc-riscv64-unknown-elf gcc-riscv64-linux-gnu qemu-user-static | head -40
find /usr /opt "$HOME/tools" -name 'riscv64*gcc' -o -name 'clang' 2>/dev/null | head -20

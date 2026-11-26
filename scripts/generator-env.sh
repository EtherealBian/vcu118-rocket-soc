# Source from bash. All downloaded/compiler files are private to this project/user cache.
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd); cy=$root/third_party/chipyard
native=${VCU_BUILD:-$HOME/.cache/vcu118-build}; tools=${VCU_TOOLS:-$HOME/.local/share/vcu118-tools}
export JAVA_HOME=$tools/jdk20 RISCV=$tools/rom-compiler
export PATH=$JAVA_HOME/bin:$tools/firtool/bin:$tools/bin:$PATH
mkdir -p "$native"/{tmp,sbt-global,sbt-boot,ivy2,coursier} "$RISCV/bin"
export COURSIER_CACHE=$native/coursier COURSIER_REPOSITORIES=https://repo.maven.apache.org/maven2
export SBT_OPTS="-Dsbt.override.build.repos=true -Dsbt.repository.config=$root/scripts/sbt.repositories -Dsbt.global.base=$native/sbt-global -Dsbt.boot.directory=$native/sbt-boot -Dsbt.ivy.home=$native/ivy2 -Dsbt.supershell=false -Dsbt.color=false"
export JAVA_TOOL_OPTIONS="-Xmx${VCU_GEN_HEAP:-6G} -Xss4M -XX:ActiveProcessorCount=${VCU_GEN_CPUS:-4} -Djava.io.tmpdir=$native/tmp -Dfile.encoding=UTF-8"

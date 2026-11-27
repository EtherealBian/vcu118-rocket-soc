# In-memory, post-synthesis classification on the isolated CPU/MIG AXI bridge only.
# No opt/place/route, DCP, bitstream, waiver or access to the FPGA.
if {$argc!=2 || ![string match {2024.2*} [version -short]]} {error {expected Vivado 2024.2, prepared inputs, fresh output}}
source [file join [file dirname [info script]] annotate-mega-gray-pointers.tcl]
lassign $argv in out; set in [file normalize $in]; set out [file normalize $out]
if {[file exists $out]} {error {expected fresh output}}; file mkdir $out; cd $out
set_param general.maxThreads 1; set_param synth.maxThreads 1
proc lines {path} {set f [open $path r];set s [split [string trim [read $f]] "\n"];close $f;return $s}
set rtfile [file join $::env(XILINX_VIVADO) scripts rt data common.tcl];set rt [open $rtfile r];if {[string length [read $rt]]<1} {error {missing Vivado synthesis runtime}};close $rt
create_project -in_memory -part xcvu9p-flga2104-2L-e
foreach sv [lines [file join $in sources.list]] {read_verilog -sv $sv}; read_verilog -sv [file join $in probe.sv]
synth_design -mode out_of_context -flatten_hierarchy rebuilt -top vcu_gray_probe -part xcvu9p-flga2104-2L-e
create_clock -name sys -period 5.714 [get_ports sys]; create_clock -name ui -period 5.000 [get_ports ui]
set_clock_groups -asynchronous -group [get_clocks sys] -group [get_clocks ui]
report_cdc -details -file [file join $out baseline.rpt]
set archive {};foreach line [lines [file join $in pins.tsv]] {lappend archive [split $line "\t"]}
if {$archive ne [::vcu118_gray::pairs axi4asource axi4asink]} {error {generated pointer paths differ from archived map}}
lassign [::vcu118_gray::annotate probe [file join $out actual.tsv]] before targets
report_cdc -details -file [file join $out candidate.rpt]
# Remove all three properties on exactly one pointer bit; the other 39 must remain classified.
set_property ASYNC_REG FALSE [get_cells [lrange $targets 0 2]];if {[::vcu118_gray::labels] ne [lsort [concat $before [lrange $targets 3 end]]]} {error {negative control scope}}
report_cdc -details -file [file join $out omitted-one-bit.rpt]; close_design
set receipt [open [file join $out completed.txt] {WRONLY CREAT EXCL}]
foreach name {actual.tsv baseline.rpt candidate.rpt omitted-one-bit.rpt} {puts $receipt "$name [file size [file join $out $name]]"}
puts $receipt VCU_GRAY_ATTR_EXPERIMENT_FINISHED_NOT_SIGNOFF;close $receipt
puts VCU_GRAY_ATTR_EXPERIMENT_FINISHED_NOT_SIGNOFF

# Exercise the actual DDR4 Tcl embedded in the pinned Scala generator, not a guessed preset.
set root [file normalize [file join [file dirname [info script]] ..]]
set dir [file join $root artifacts ddr-preflight]
file mkdir $dir
set ipdir [file join $dir ip]
file mkdir $ipdir
set sfile [file join $root third_party chipyard fpga fpga-shells src main scala ip xilinx vcu118mig vcu118mig.scala]
set f [open $sfile r]; set s [read $f]; close $f
if {![regexp {"vcu118mig\.vivado\.tcl",\s*"""(.*?)"""} $s -> code]} {error "upstream DDR4 template changed"}
set fh [open [file join $dir upstream-ddr.tcl] w]; puts $fh $code; close $fh
create_project -in_memory -part xcvu9p-flga2104-2L-e
source [file join $dir upstream-ddr.tcl]
set ip [get_ips vcu118mig]; puts "IPDEF=[get_property IPDEF $ip]"; generate_target instantiation_template $ip
report_ip_status -file [file join $dir ip-status.rpt]
puts "DDR4_CONFIG_ACCEPTED_NOT_SYNTHESIZED"

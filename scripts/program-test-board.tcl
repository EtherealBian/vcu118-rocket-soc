# Program one already reviewed image into volatile configuration only; coordinate UART epoch.
if {$argc != 7} {error {usage: bit cable-serial device slr0-dna armed-file ack-file programmed-file}}
lassign $argv bit serial name dna arm ack done
if {![file isfile $bit] || [file extension $bit] ne ".bit"} {error {missing input bitstream}}
foreach p [list $arm $ack $done] {if {[file exists $p]} {error "stale handoff file $p"}}
open_hw_manager; connect_hw_server -url localhost:3121
try {
 set targets {}; foreach t [get_hw_targets -quiet] {if {[file tail $t] eq $serial} {lappend targets $t}}
 if {[llength $targets]!=1} {error "unexpected cable match: $targets"}; current_hw_target [lindex $targets 0]; open_hw_target
 try {
  set devs [get_hw_devices -quiet]; if {[llength $devs]!=1 || [lindex $devs 0] ne $name} {error "wrong chain: $devs"}
  set d [current_hw_device [lindex $devs 0]]; refresh_hw_device -update_hw_probes false $d
  if {![string equal -nocase $dna [get_property REGISTER.DNA.SLR0 $d]] || [get_property PART $d] ne "xcvu9p"} {error {part or silicon DNA mismatch; not programming}}
  set_property PROGRAM.FILE $bit $d; close [open $arm {WRONLY CREAT EXCL}]; set deadline [expr {[clock milliseconds]+15000}]
  while {![file exists $ack]} {if {[clock milliseconds]>$deadline} {error {UART collector did not acknowledge arm; not programming}}; after 50}
  puts "VOLATILE_PROGRAM_START cable=$serial device=$d"; program_hw_devices $d; refresh_hw_device -update_hw_probes false $d
  foreach i {0 1 2} {
   foreach {suffix expected} {{BIT[14]_DONE_PIN} 1 {BIT[00]_CRC_ERROR} 0} {
    set k REGISTER.CONFIG_STATUS.SLR$i.$suffix; set val [get_property $k $d]; puts "PROGRAM_READBACK $k=$val"; if {$val ne $expected} {error "configuration status mismatch $k"}
   }
  }; close [open $done {WRONLY CREAT EXCL}]; puts VOLATILE_PROGRAM_AND_READBACK_PASS
 } finally {close_hw_target}
} finally {disconnect_hw_server; close_hw_manager}

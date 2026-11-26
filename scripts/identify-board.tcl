if {[llength $argv] != 2} {error {expected exact cable serial and device name}}
lassign $argv serial name
open_hw_manager
connect_hw_server -url localhost:3121
set hit {}
foreach t [get_hw_targets -quiet] {if {[file tail $t] eq $serial} {lappend hit $t}}
if {[llength $hit] != 1} {error "refusing ambiguous cable: $hit"}
current_hw_target [lindex $hit 0]; open_hw_target
set ds [get_hw_devices -quiet]; if {[llength $ds] != 1 || [lindex $ds 0] ne $name} {error "unexpected device chain: $ds"}
set d [current_hw_device [lindex $ds 0]]
refresh_hw_device -update_hw_probes false $d
foreach p [lsort [list_property $d]] {if {[regexp {^(PART$|NAME$|PROGRAM\.IS_SUPPORTED$|REGISTER\.(IDCODE|CONFIG_STATUS|BOOT_STATUS|USR_ACCESS|DNA)|IS_PROGRAMMED$)} $p]} {puts "LIVE_PROP $p=[get_property $p $d]"}}
puts "JTAG_READONLY_PASS target=[current_hw_target] device=$d part=[get_property PART $d]"
close_hw_target; disconnect_hw_server; close_hw_manager

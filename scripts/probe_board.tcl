puts "VIVADO=[version -short]"
set parts [get_parts -quiet xcvu9p-flga2104-2L-e]
puts "VCU118_PART=$parts"
puts "VCU118_BOARD=[get_board_parts -quiet *:vcu118:*]"
if {![llength $parts]} {exit 2}
open_hw_manager
if {[catch {connect_hw_server -url localhost:3121} msg]} {puts "HW_SERVER_ERROR=$msg"; exit 3}
set ts [get_hw_targets -quiet]
puts "JTAG_TARGETS=$ts"
foreach t $ts { if {[catch {current_hw_target $t; open_hw_target; puts "JTAG_DEVICES=[get_hw_devices -quiet]"; close_hw_target} msg]} {puts "JTAG_ENUM_ERROR=$msg"} }
disconnect_hw_server
close_hw_manager

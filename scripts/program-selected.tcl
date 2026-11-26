# Volatile programming only. Exactly match the operator-selected target and device.
# Run only after reviewing the bitstream's implementation reports. Does not erase PROM or SD.
if {$argc != 3} {error "usage: bitstream exact_hw_target_name exact_vu9p_hw_device_name"}
lassign $argv bit targetName devName;set bit [file normalize $bit]; if {![file isfile $bit] || [file extension $bit] ne ".bit"} {error "invalid .bit input"}
open_hw_manager; connect_hw_server -url localhost:3121
try {
 set matches {}; foreach item [get_hw_targets -quiet] {if {[get_property NAME $item] eq $targetName} {lappend matches $item}}
 if {[llength $matches]!=1} {error "expected exactly one matching hardware target; enumerate before retrying"}; current_hw_target [lindex $matches 0];open_hw_target
 try {
  set ds {};foreach d [get_hw_devices -quiet] {if {[get_property NAME $d] eq $devName && [string tolower [get_property PART $d]] eq "xcvu9p"} {lappend ds $d}}
  if {[llength $ds]!=1} {error "matching VU9P device not found on selected target"};set d [lindex $ds 0];current_hw_device $d
  puts "PROGRAM_SELECTED_TARGET=$targetName DEVICE=$devName PART=[get_property PART $d] BIT=$bit"
  set_property PROGRAM.FILE $bit $d; program_hw_devices $d;refresh_hw_device $d
  puts "VOLATILE_PROGRAM_COMMAND_COMPLETED_NOT_BOOT_VALIDATION"
 } finally {close_hw_target}
} finally {disconnect_hw_server; close_hw_manager}

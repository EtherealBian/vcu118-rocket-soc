# Read the current design through the configuration JTAG, without reprogramming,
# resetting the MIG, running traffic, or starting a margin scan. Output is private.
if {$argc != 5} {error {usage: exact-cable device slr0-dna present|absent fresh-output-dir}}
lassign $argv cable name dna expectation out
if {$expectation ni {present absent} || ![regexp -nocase {^0x[0-9a-f]+$} $dna] || [file exists $out]} {error {invalid arguments or stale output}}
set out [file normalize $out]; file mkdir $out
open_hw_manager; connect_hw_server -url localhost:3121
try {
 set matches {}; foreach t [get_hw_targets] {if {[file tail $t] eq $cable} {lappend matches $t}}
 if {[llength $matches]!=1} {error {cable not uniquely identified}}
 current_hw_target [lindex $matches 0]; open_hw_target
 try {
  set devs [get_hw_devices]; if {[llength $devs]!=1 || [lindex $devs 0] ne $name} {error {unexpected device chain}}
  set d [current_hw_device [lindex $devs 0]]; refresh_hw_device $d
  if {[get_property PART $d] ne {xcvu9p} || ![string equal -nocase $dna [get_property REGISTER.DNA.SLR0 $d]]} {error {silicon mismatch}}
  foreach i {0 1 2} {foreach {p expected} {{BIT[14]_DONE_PIN} 1 {BIT[00]_CRC_ERROR} 0} {
   if {[get_property REGISTER.CONFIG_STATUS.SLR$i.$p $d] ne $expected} {error "configuration status mismatch for SLR$i $p"}
  }}
  set migs [get_hw_migs -of_objects $d]; puts "LIVE_MIG_OBJECTS [llength $migs]"
  if {$expectation eq {absent}} {
   if {[llength $migs]!=0} {error {expected a design without MIG; check selected image}}
   puts LIVE_MIG_NOT_EXPOSED_NO_CALIBRATION_CLAIM
  } else {
   if {[llength $migs]!=1} {error {no single visible MIG: calibration unknown; no hardware change made}}
   set m [lindex $migs 0]; refresh_hw_mig $m
   report_hw_mig -file [file join $out live-mig.rpt] $m
   report_property -all -file [file join $out live-mig-properties.rpt] $m
   if {![file size [file join $out live-mig.rpt]]} {error {empty calibration report}}
   puts LIVE_MIG_REPORT_CAPTURED_REVIEW_CALIBRATION_FIELDS
  }
 } finally {close_hw_target}
} finally {disconnect_hw_server; close_hw_manager}

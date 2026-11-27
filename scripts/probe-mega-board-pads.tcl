# Compare one fixed package-boundary fixture, not a routed SoC or board test.
# Run separately for stock and typed: -tclargs prepared-dir new-output-dir case
if {$argc != 3 || [lindex $argv 2] ni {stock typed} || ![string match {2024.2*} [version -short]]} {error {require Vivado 2024.2, prepared-dir, new-output-dir and stock|typed}}
lassign $argv in out which; set in [file normalize $in]; set out [file normalize $out]
set checker [file join [file dirname [file normalize [info script]]] test-mega-board-pads.py]
if {[exec python -I -B $checker check $in] ne {"PAD_INPUTS_VERIFIED"} || [file exists $out]} {error {invalid inputs or existing output}}
file mkdir $out; cd $out; set_param general.maxThreads 2
set part xcvu9p-flga2104-2L-e
create_project -in_memory -part $part
foreach f {AnalogToUInt_1.v UIntToAnalog_1.v} {read_verilog [file join $in $f]}
read_verilog -sv [file join $in $which.sv]; read_xdc [file join $in pads.xdc]
synth_design -top io_fixture -part $part
write_checkpoint synthesized.dcp
set pads {uart_rxd AW25 IN INBUF sdio_spi_dat_0 AW15 IN INBUF jtag_jtag_TCK AL12 IN INBUF jtag_jtag_TDI AP15 IN INBUF jtag_jtag_TMS AN15 IN INBUF uart_txd BB21 OUT OBUF sdio_spi_clk AV15 OUT OBUF sdio_spi_cs AY15 OUT OBUF sdio_spi_dat_3 AY14 OUT OBUF jtag_jtag_TDO AM12 OUT OBUF}
set f [open ports.tsv w]; puts $f "pad\tpackage_pin\tdirection\tstandard\tprimitive\tprimitive_pin\tdrive_enable"
foreach {name pin expected buf} $pads {
    set port [get_ports $name]; set net [get_nets -of_objects $port]; set pins [get_pins -leaf -of_objects $net]; set dir [get_property DIRECTION $port]
    set ball [get_property PACKAGE_PIN $port]; set std [get_property IOSTANDARD $port]
    if {[llength $port]!=1 || [llength $net]!=1 || [llength $pins]!=1 || $ball ne $pin || $std ne "LVCMOS18"} {error "unaccounted boundary $name $ball $std $net $pins"}
    set cell [get_cells -of_objects $pins]; set ref [get_property REF_NAME $cell]; set bp [get_property REF_PIN_NAME $pins]
    set enable -
    if {$ref eq "OBUFT"} {
        set t [get_pins -of_objects $cell -filter {REF_PIN_NAME == T}]
        set tn [get_nets -of_objects $t]; set drv [get_pins -leaf -of_objects $tn -filter {DIRECTION == OUT}]
        set src [get_cells -of_objects $drv]; set val [get_property REF_NAME $src]
        if {[llength $t]!=1 || [llength $drv]!=1} {error "ambiguous enable: $name"}
        if {$val eq "GND" && [get_property REF_PIN_NAME $drv] eq "G"} {
            set enable T=GND
        } elseif {$val eq "LUT1" && [string tolower [get_property INIT $src]] eq "2'h1" && [get_property REF_PIN_NAME $drv] eq "O"} {
            set i [get_pins -of_objects $src -filter {REF_PIN_NAME == I0}]
            set d [get_pins -leaf -of_objects [get_nets -of_objects $i] -filter {DIRECTION == OUT}]
            if {[llength $i]!=1 || [llength $d]!=1 || [get_property REF_NAME [get_cells -of_objects $d]] ne "VCC" || [get_property REF_PIN_NAME $d] ne "P"} {error "unexpected inverter input: $name $d"}
            set enable T=NOT_VCC
        } else {error "not always driving: $name $t $tn $drv $val"}
    }
    puts $f [join [list $name $ball $dir $std $ref $bp $enable] "\t"]
    if {$dir ne [expr {$which eq "stock" ? "INOUT" : $expected}] || !(($ref eq $buf) || ($buf eq "OBUF" && $ref eq "OBUFT" && $enable in {T=GND T=NOT_VCC})) || $bp ne [expr {$expected eq "IN" ? "PAD" : "O"}]} {error "unexpected native buffer for $which $name: $dir $ref $bp"}
}
close $f
foreach {cmd rule} {get_drc_checks RPBF-3 get_methodology_checks HPDR-1} {
    set c [$cmd -quiet $rule]; if {[llength $c]!=1 || ![get_property IS_ENABLED $c]} {error "missing/disabled native rule $rule"}
    report_property -all $c -file $rule-properties.txt
}
report_drc -checks [get_drc_checks RPBF-3] -file drc.rpt
report_methodology -checks [get_methodology_checks HPDR-1] -file methodology.rpt
puts "PAD_PROBE_FINISHED $which synthesized (no placement or route)"

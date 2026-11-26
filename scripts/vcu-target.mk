.PHONY: vcu118-rtl-manifest
vcu118-rtl-manifest: $(synth_list_f)
	@echo "MANIFEST_READY=$(synth_list_f)"

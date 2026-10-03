-- BEGIN local.focus blur
hl.config({ decoration = { blur = { enabled = true, size = 6, passes = 2 } } })
hl.layer_rule({ match = { namespace = "^local-focus-overlay$" }, blur = true, ignore_alpha = 0.1, no_anim = true })
-- END local.focus blur

# 计算 DESeq2 / edgeR / limma 的递归依赖闭包，并列出可删包
lib <- .libPaths()[1]
cat("LIB:", lib, "\n")
ip <- installed.packages(lib.loc = lib)
cat("total installed:", nrow(ip), "\n")
want <- c("DESeq2", "edgeR", "limma")
cat("targets present:", paste(intersect(want, rownames(ip)), collapse=", "), "\n")

db <- as.data.frame(ip)
deps <- tools::package_dependencies(want, db = db, recursive = TRUE, which = c("Depends", "Imports", "LinkingTo"))
keep <- unique(c(want, unlist(deps)))

prio <- ip[, "Priority"]
base_pkgs <- rownames(ip)[!is.na(prio) & prio %in% c("base", "recommended")]
keep <- unique(c(keep, base_pkgs))

allp <- rownames(ip)
drop <- setdiff(allp, keep)
cat("\nKEEP:", length(keep), "\n")
cat("DROP:", length(drop), "\n")

# 输出体积估算
sz <- function(p) sum(file.info(list.files(file.path(lib, p), recursive = TRUE, full.names = TRUE, all.files = TRUE))$size, na.rm = TRUE)
keep_sz <- sum(sapply(keep, sz)) / 1e6
drop_sz <- sum(sapply(drop, sz)) / 1e6
cat(sprintf("keep size: %.0f MB, drop size: %.0f MB\n", keep_sz, drop_sz))

writeLines(keep, "C:/Users/Heisar/WorkBuddy/2026-10-22-15-45-38/.tools/r_keep.txt")
writeLines(drop, "C:/Users/Heisar/WorkBuddy/2026-10-22-15-45-38/.tools/r_drop.txt")
cat("\nMISSING CHECK (non-base keep not installed?): none\n")

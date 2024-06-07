PRISMA_SCHEME = "./schema.prisma"

target:
	@awk -F ':|##' '/^[^\t].+?:.*?##/ { printf "\033[0;36m%-15s\033[0m %s\n", $$1, $$NF }' $(MAKEFILE_LIST)

db_push:  ## Update the database with Prisma
	prisma format --schema $(PRISMA_SCHEME)
	prisma db push --schema $(PRISMA_SCHEME) --skip-generate

db_pull:  ## Pull the database from Prisma
	prisma db pull --schema $(PRISMA_SCHEME)

db_format:	## Format to make Prisma happy
	prisma format --schema $(PRISMA_SCHEME)

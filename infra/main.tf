module "network" {
  source = "./modules/network"

  name              = var.name
  region            = var.region
  endpoint_az_count = var.endpoint_az_count
}

module "storage" {
  source = "./modules/storage"

  name = var.name
}

module "edge" {
  source = "./modules/edge"

  name              = var.name
  vpc_id            = module.network.vpc_id
  vpc_cidr          = module.network.vpc_cidr
  public_subnet_ids = module.network.public_subnet_ids
  domain_name       = var.domain_name
}

module "compute" {
  source = "./modules/compute"

  name                    = var.name
  region                  = var.region
  vpc_id                  = module.network.vpc_id
  vpc_cidr                = module.network.vpc_cidr
  private_subnet_ids      = module.network.private_subnet_ids
  s3_prefix_list_id       = module.network.s3_prefix_list_id
  dynamodb_prefix_list_id = module.network.dynamodb_prefix_list_id
  alb_security_group_id   = module.edge.alb_security_group_id
  target_group_arn        = module.edge.target_group_arn
  api_image               = "${module.storage.repository_urls["api"]}:${var.image_tag}"
  worker_image            = "${module.storage.repository_urls["worker"]}:${var.image_tag}"
  api_desired_count       = var.api_desired_count
  worker_desired_count    = var.worker_desired_count
  bucket_name             = module.storage.bucket_name
  bucket_arn              = module.storage.bucket_arn
  table_name              = module.storage.table_name
  table_arn               = module.storage.table_arn
  queue_url               = module.storage.queue_url
  queue_arn               = module.storage.queue_arn
}

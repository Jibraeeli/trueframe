output "vpc_id" {
  value = aws_vpc.main.id
}

output "vpc_cidr" {
  value = aws_vpc.main.cidr_block
}

output "public_subnet_ids" {
  value = aws_subnet.public[*].id
}

output "private_subnet_ids" {
  value = aws_subnet.private[*].id
}

output "s3_prefix_list_id" {
  value = aws_vpc_endpoint.gateway["s3"].prefix_list_id
}

output "dynamodb_prefix_list_id" {
  value = aws_vpc_endpoint.gateway["dynamodb"].prefix_list_id
}

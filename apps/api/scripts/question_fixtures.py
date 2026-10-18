"""Self-authored SAA-C03 style questions used until generation (M5) exists."""

# (task_statement_code, stem, {A..D: text}, correct_option, explanation)
QUESTIONS = [
    # --- Domain 1: Design Secure Architectures ---
    (
        "1.1",
        "An application on Amazon EC2 needs to read objects from an Amazon S3 bucket. "
        "The company does not want to store long-term credentials on the instance. "
        "What should a solutions architect do?",
        {
            "A": "Store an IAM user's access keys in an encrypted file on the instance.",
            "B": "Attach an IAM role with the required S3 permissions to the instance through an instance profile.",
            "C": "Embed the access keys in the application's environment variables.",
            "D": "Make the S3 bucket public so no credentials are needed.",
        },
        "B",
        "An IAM role delivered through an instance profile provides temporary credentials that are "
        "rotated automatically, so no long-term secrets are stored on the instance.",
    ),
    (
        "1.1",
        "A company needs to give an application in Account A access to resources in Account B while "
        "following least-privilege principles and avoiding long-term credentials. Which solution meets "
        "these requirements?",
        {
            "A": "Create an IAM user in Account B and share its access keys with Account A.",
            "B": "Copy the resources into Account A.",
            "C": "Create an IAM role in Account B that trusts Account A, and have the application assume the role.",
            "D": "Attach the AdministratorAccess policy to a role in Account A.",
        },
        "C",
        "A cross-account IAM role with a trust policy lets the application obtain temporary credentials "
        "through sts:AssumeRole, scoped to only the permissions the role grants.",
    ),
    (
        "1.2",
        "An application runs in private subnets and must access Amazon DynamoDB. The company requires "
        "that this traffic does not traverse the public internet. Which solution is the MOST cost-effective?",
        {
            "A": "Create a NAT gateway in a public subnet and route DynamoDB traffic through it.",
            "B": "Create a gateway VPC endpoint for DynamoDB and update the route tables.",
            "C": "Create an AWS Site-to-Site VPN to DynamoDB.",
            "D": "Place the application in a public subnet with an internet gateway.",
        },
        "B",
        "A gateway VPC endpoint keeps DynamoDB traffic on the AWS network and has no hourly or "
        "data-processing charge, unlike a NAT gateway.",
    ),
    (
        "1.2",
        "A web application behind an Application Load Balancer is receiving SQL injection and "
        "cross-site scripting attempts. Which service should be used to block these requests?",
        {
            "A": "AWS Shield Standard",
            "B": "Amazon GuardDuty",
            "C": "Security groups on the load balancer",
            "D": "AWS WAF with a web ACL associated with the load balancer",
        },
        "D",
        "AWS WAF inspects HTTP(S) requests and its managed rules block common attacks such as SQL "
        "injection and XSS. It can be associated directly with an Application Load Balancer.",
    ),
    (
        "1.3",
        "A company must encrypt data in Amazon S3 using keys that it controls and must be able to audit "
        "every use of the keys. Which solution meets these requirements?",
        {
            "A": "Server-side encryption with Amazon S3 managed keys (SSE-S3).",
            "B": "Server-side encryption with a customer managed AWS KMS key (SSE-KMS), with AWS CloudTrail enabled.",
            "C": "Client-side Base64 encoding of the objects before upload.",
            "D": "Enable S3 Versioning on the bucket.",
        },
        "B",
        "SSE-KMS with a customer managed key gives the company control over the key policy, and AWS KMS "
        "key usage is recorded in AWS CloudTrail for auditing.",
    ),
    (
        "1.3",
        "A company stores database credentials in application configuration files and wants them "
        "rotated automatically every 30 days without code changes. Which service should be used?",
        {
            "A": "AWS Secrets Manager with automatic rotation enabled",
            "B": "Amazon S3 with versioning",
            "C": "AWS Config",
            "D": "Amazon Cognito user pools",
        },
        "A",
        "AWS Secrets Manager stores secrets and can rotate supported database credentials on a schedule "
        "using a Lambda function, while applications retrieve the current secret at runtime.",
    ),
    # --- Domain 2: Design Resilient Architectures ---
    (
        "2.1",
        "An e-commerce site experiences unpredictable traffic spikes that overwhelm the order-processing "
        "workers. Orders must not be lost. What should a solutions architect recommend?",
        {
            "A": "Increase the instance size of the order-processing workers.",
            "B": "Have the web tier call the workers synchronously over HTTP.",
            "C": "Store the orders in memory on the web servers.",
            "D": "Place an Amazon SQS queue between the web tier and the workers.",
        },
        "D",
        "SQS decouples the tiers: the queue durably buffers orders during spikes, and the workers "
        "process messages at their own pace.",
    ),
    (
        "2.1",
        "A single event must be delivered to several independent downstream systems, each processing it "
        "at its own pace. Which architecture meets this requirement?",
        {
            "A": "Publish the event to an Amazon SNS topic with a separate Amazon SQS queue subscribed for each system.",
            "B": "Send the event to a single Amazon SQS queue read by all systems.",
            "C": "Write the event to a shared Amazon EFS file system.",
            "D": "Invoke each system synchronously from the producer.",
        },
        "A",
        "SNS fans out one message to many subscribers. Giving each consumer its own SQS queue lets each "
        "process independently and durably.",
    ),
    (
        "2.2",
        "A production Amazon RDS for MySQL database must remain available if an Availability Zone "
        "fails, with automatic failover and no application changes. What should be configured?",
        {
            "A": "An RDS read replica in the same Availability Zone.",
            "B": "A Multi-AZ deployment.",
            "C": "Daily manual snapshots.",
            "D": "A larger DB instance class.",
        },
        "B",
        "A Multi-AZ deployment maintains a synchronous standby in another AZ and fails over "
        "automatically, keeping the same endpoint.",
    ),
    (
        "2.2",
        "A web application runs on Amazon EC2 instances behind an Application Load Balancer. The "
        "application must stay available if one Availability Zone becomes unavailable. What should be done?",
        {
            "A": "Run all instances in one Availability Zone and use larger instances.",
            "B": "Use an Elastic IP address attached to a single instance.",
            "C": "Configure an Auto Scaling group that spans multiple Availability Zones behind the load balancer.",
            "D": "Back up the instances nightly with AMIs.",
        },
        "C",
        "An Auto Scaling group across multiple AZs replaces failed capacity, and the load balancer sends "
        "traffic only to healthy instances in the remaining zones.",
    ),
    # --- Domain 3: Design High-Performing Architectures ---
    (
        "3.1",
        "Linux-based applications running on Amazon EC2 instances in multiple Availability Zones need "
        "concurrent access to a shared POSIX-compliant file system. Which storage should be used?",
        {
            "A": "Amazon EBS Multi-Attach volumes",
            "B": "Amazon S3",
            "C": "Amazon EFS",
            "D": "Instance store volumes",
        },
        "C",
        "Amazon EFS is a managed NFS file system that is POSIX-compliant and can be mounted concurrently "
        "by instances across multiple Availability Zones.",
    ),
    (
        "3.1",
        "A mission-critical database on Amazon EC2 requires sustained high IOPS and consistent "
        "low-latency block storage. Which EBS volume type is MOST appropriate?",
        {
            "A": "Throughput Optimized HDD (st1)",
            "B": "Cold HDD (sc1)",
            "C": "General Purpose SSD (gp2) with burst credits",
            "D": "Provisioned IOPS SSD (io2)",
        },
        "D",
        "Provisioned IOPS SSD volumes are designed for I/O-intensive workloads that need sustained, "
        "predictable IOPS and low latency.",
    ),
    (
        "3.3",
        "A reporting application is placing heavy read load on an Amazon RDS database, slowing down the "
        "primary workload. How can the read load be offloaded with the LEAST operational effort?",
        {
            "A": "Create one or more read replicas and direct reporting queries to them.",
            "B": "Migrate the database to Amazon EC2 and manage replication manually.",
            "C": "Schedule reports to run only at night.",
            "D": "Disable automated backups.",
        },
        "A",
        "RDS read replicas use asynchronous replication to serve read traffic, offloading the primary "
        "instance with minimal operational overhead.",
    ),
    (
        "3.3",
        "A gaming application reads the same small items from Amazon DynamoDB very frequently and needs "
        "response times in microseconds. Which solution requires the LEAST application change?",
        {
            "A": "Increase the table's provisioned read capacity.",
            "B": "Add Amazon DynamoDB Accelerator (DAX) in front of the table.",
            "C": "Migrate the data to Amazon S3.",
            "D": "Enable DynamoDB Streams.",
        },
        "B",
        "DAX is an API-compatible, in-memory cache for DynamoDB that delivers microsecond read latency "
        "for cached items.",
    ),
    (
        "3.4",
        "A company serves static content to a global audience from an Amazon S3 bucket and users far "
        "from the Region experience high latency. What should a solutions architect do?",
        {
            "A": "Enable S3 Versioning.",
            "B": "Increase the S3 bucket's storage class to Standard-IA.",
            "C": "Create an Amazon CloudFront distribution with the bucket as the origin.",
            "D": "Move the bucket to a larger Region.",
        },
        "C",
        "CloudFront caches content at edge locations close to users, reducing latency for a global audience.",
    ),
    # --- Domain 4: Design Cost-Optimized Architectures ---
    (
        "4.1",
        "A company stores data in Amazon S3 with unknown and changing access patterns. It wants to "
        "minimize storage costs automatically without retrieval fees or performance impact. Which option "
        "should be chosen?",
        {
            "A": "S3 Standard-Infrequent Access",
            "B": "S3 Intelligent-Tiering",
            "C": "S3 One Zone-Infrequent Access",
            "D": "S3 Glacier Deep Archive",
        },
        "B",
        "S3 Intelligent-Tiering moves objects between access tiers automatically based on usage, with no "
        "retrieval fees, which suits unknown or changing access patterns.",
    ),
    (
        "4.1",
        "A company must retain compliance records for 10 years. The records are almost never accessed, "
        "and a retrieval time of up to 12 hours is acceptable. Which storage class is the MOST cost-effective?",
        {
            "A": "S3 Standard",
            "B": "S3 Glacier Deep Archive",
            "C": "S3 Glacier Instant Retrieval",
            "D": "S3 Standard-Infrequent Access",
        },
        "B",
        "S3 Glacier Deep Archive has the lowest storage cost of the S3 classes and standard retrievals "
        "complete within 12 hours.",
    ),
    (
        "4.2",
        "A company runs fault-tolerant, stateless batch processing jobs that can be interrupted and have "
        "flexible start times. Which Amazon EC2 purchasing option minimizes cost?",
        {
            "A": "On-Demand Instances",
            "B": "Dedicated Hosts",
            "C": "Spot Instances",
            "D": "A 3-year Reserved Instance",
        },
        "C",
        "Spot Instances offer steep discounts for spare capacity and suit workloads that tolerate "
        "interruption.",
    ),
    (
        "4.2",
        "A company runs a steady-state production workload on Amazon EC2 that will be needed for at least "
        "three years. Which option provides the LOWEST cost while keeping flexibility across instance families?",
        {
            "A": "On-Demand Instances",
            "B": "Spot Instances",
            "C": "Dedicated Hosts billed On-Demand",
            "D": "A 3-year Compute Savings Plan",
        },
        "D",
        "Compute Savings Plans give large discounts for a one- or three-year commitment and apply across "
        "instance families, Regions, and even Fargate and Lambda.",
    ),
    (
        "4.4",
        "Instances in private subnets download large volumes of data from Amazon S3 through a NAT gateway, "
        "generating high data-processing charges. How can the cost be reduced?",
        {
            "A": "Add a second NAT gateway.",
            "B": "Move the instances to public subnets with Elastic IP addresses.",
            "C": "Use an AWS Direct Connect connection.",
            "D": "Create a gateway VPC endpoint for Amazon S3 and route S3 traffic through it.",
        },
        "D",
        "A gateway VPC endpoint for S3 carries traffic privately with no hourly or data-processing charge, "
        "removing the NAT gateway from the path.",
    ),
]

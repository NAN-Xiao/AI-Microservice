package com.example.msgqueue;

import com.example.msgqueue.config.QueueProperties;
import com.example.msgqueue.config.ServerPortsProperties;
import com.example.msgqueue.config.SeeThroughProperties;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.cloud.client.discovery.EnableDiscoveryClient;

@SpringBootApplication
@EnableDiscoveryClient
@EnableConfigurationProperties({QueueProperties.class, SeeThroughProperties.class, ServerPortsProperties.class})
public class MsgQueueApplication {

    public static void main(String[] args) {
        SpringApplication.run(MsgQueueApplication.class, args);
    }
}


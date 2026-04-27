package com.example.msgqueue;

import com.example.msgqueue.config.QueueProperties;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.EnableConfigurationProperties;

@SpringBootApplication
@EnableConfigurationProperties(QueueProperties.class)
public class MsgQueueApplication {

    public static void main(String[] args) {
        SpringApplication.run(MsgQueueApplication.class, args);
    }
}


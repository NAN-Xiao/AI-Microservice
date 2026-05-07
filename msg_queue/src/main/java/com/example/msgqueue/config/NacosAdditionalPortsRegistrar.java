package com.example.msgqueue.config;

import com.alibaba.nacos.api.NacosFactory;
import com.alibaba.nacos.api.exception.NacosException;
import com.alibaba.nacos.api.naming.NamingService;
import jakarta.annotation.PreDestroy;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.env.Environment;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.event.EventListener;
import org.springframework.stereotype.Component;

import java.net.InetAddress;
import java.net.UnknownHostException;
import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Properties;
import java.util.Set;

@Component
public class NacosAdditionalPortsRegistrar {

    private static final Logger log = LoggerFactory.getLogger(NacosAdditionalPortsRegistrar.class);

    private final ServerPortsProperties serverPortsProperties;
    private final Environment environment;

    @Value("${spring.application.name:msg-queue-service}")
    private String serviceName;

    @Value("${spring.cloud.nacos.discovery.enabled:true}")
    private boolean nacosEnabled;

    @Value("${spring.cloud.nacos.discovery.register-additional-ports:false}")
    private boolean registerAdditionalPorts;

    @Value("${spring.cloud.nacos.discovery.server-addr:127.0.0.1:8848}")
    private String serverAddr;

    @Value("${spring.cloud.nacos.discovery.namespace:}")
    private String namespace;

    @Value("${spring.cloud.nacos.discovery.group:DEFAULT_GROUP}")
    private String groupName;

    @Value("${spring.cloud.nacos.discovery.cluster-name:DEFAULT}")
    private String clusterName;

    @Value("${spring.cloud.nacos.discovery.username:nacos}")
    private String username;

    @Value("${spring.cloud.nacos.discovery.password:nacos}")
    private String password;

    @Value("${spring.cloud.nacos.discovery.ip:}")
    private String configuredIp;

    private NamingService namingService;
    private final List<Integer> registeredPorts = new ArrayList<>();

    public NacosAdditionalPortsRegistrar(ServerPortsProperties serverPortsProperties, Environment environment) {
        this.serverPortsProperties = serverPortsProperties;
        this.environment = environment;
    }

    @EventListener(ApplicationReadyEvent.class)
    public void register() {
        if (!nacosEnabled || !registerAdditionalPorts) {
            log.info("Additional Nacos ports registration disabled.");
            return;
        }

        Set<Integer> ports = new LinkedHashSet<>(serverPortsProperties.getAdditionalPorts());
        Integer mainPort = environment.getProperty("local.server.port", Integer.class);
        ports.remove(mainPort);
        if (ports.isEmpty()) {
            return;
        }

        try {
            namingService = NacosFactory.createNamingService(buildProperties());
            String ip = resolveIp();
            for (Integer port : ports) {
                namingService.registerInstance(serviceName, groupName, ip, port, clusterName);
                registeredPorts.add(port);
                log.info("Registered additional Nacos instance: serviceName={} group={} ip={} port={}",
                        serviceName, groupName, ip, port);
            }
        } catch (Exception ex) {
            log.error("Failed to register additional Nacos ports for service {}", serviceName, ex);
        }
    }

    @PreDestroy
    public void deregister() {
        if (namingService == null || registeredPorts.isEmpty()) {
            return;
        }

        try {
            String ip = resolveIp();
            for (Integer port : registeredPorts) {
                try {
                    namingService.deregisterInstance(serviceName, groupName, ip, port, clusterName);
                    log.info("Deregistered additional Nacos instance: serviceName={} group={} ip={} port={}",
                            serviceName, groupName, ip, port);
                } catch (NacosException ex) {
                    log.warn("Failed to deregister additional Nacos port {}", port, ex);
                }
            }
        } catch (Exception ex) {
            log.warn("Failed to resolve local ip during additional Nacos deregistration", ex);
        }
    }

    private Properties buildProperties() {
        Properties properties = new Properties();
        properties.put("serverAddr", serverAddr);
        if (!namespace.isBlank()) {
            properties.put("namespace", namespace);
        }
        if (!username.isBlank()) {
            properties.put("username", username);
        }
        if (!password.isBlank()) {
            properties.put("password", password);
        }
        return properties;
    }

    private String resolveIp() throws UnknownHostException {
        if (configuredIp != null && !configuredIp.isBlank()) {
            return configuredIp.trim();
        }
        return InetAddress.getLocalHost().getHostAddress();
    }
}

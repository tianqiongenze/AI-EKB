package main

import (
	"context"

	"google.golang.org/grpc"
	"google.golang.org/protobuf/types/known/structpb"
)

type CapabilityGatewayServiceClient interface {
	EvaluatePolicy(ctx context.Context, in *structpb.Struct, opts ...grpc.CallOption) (*structpb.Struct, error)
	AggregateInsights(ctx context.Context, in *structpb.Struct, opts ...grpc.CallOption) (*structpb.Struct, error)
	GovernanceDecision(ctx context.Context, in *structpb.Struct, opts ...grpc.CallOption) (*structpb.Struct, error)
}

type capabilityGatewayServiceClient struct {
	connection grpc.ClientConnInterface
}

func NewCapabilityGatewayServiceClient(connection grpc.ClientConnInterface) CapabilityGatewayServiceClient {
	return &capabilityGatewayServiceClient{connection: connection}
}

func (client *capabilityGatewayServiceClient) EvaluatePolicy(ctx context.Context, in *structpb.Struct, opts ...grpc.CallOption) (*structpb.Struct, error) {
	response := &structpb.Struct{}
	err := client.connection.Invoke(ctx, "/ekb.contracts.CapabilityGatewayService/EvaluatePolicy", in, response, opts...)
	if err != nil {
		return nil, err
	}
	return response, nil
}

func (client *capabilityGatewayServiceClient) AggregateInsights(ctx context.Context, in *structpb.Struct, opts ...grpc.CallOption) (*structpb.Struct, error) {
	response := &structpb.Struct{}
	err := client.connection.Invoke(ctx, "/ekb.contracts.CapabilityGatewayService/AggregateInsights", in, response, opts...)
	if err != nil {
		return nil, err
	}
	return response, nil
}

func (client *capabilityGatewayServiceClient) GovernanceDecision(ctx context.Context, in *structpb.Struct, opts ...grpc.CallOption) (*structpb.Struct, error) {
	response := &structpb.Struct{}
	err := client.connection.Invoke(ctx, "/ekb.contracts.CapabilityGatewayService/GovernanceDecision", in, response, opts...)
	if err != nil {
		return nil, err
	}
	return response, nil
}

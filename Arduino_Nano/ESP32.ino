#include <WiFi.h>
#include <WebSocketsClient.h>


const char* ssid = "OPPO A55";
const char* password = "Kish@2476";


#define ECG_PIN 36   // VP GPIO36


WebSocketsClient webSocket;


unsigned long lastSampleTime = 0;

#define SAMPLE_INTERVAL 2778   // 360Hz


void setup() {

  Serial.begin(115200);

  analogReadResolution(12);


  WiFi.begin(ssid, password);

  Serial.print("Connecting");

  while(WiFi.status() != WL_CONNECTED){

    delay(500);
    Serial.print(".");
  }


  Serial.println();
  Serial.println("WiFi Connected");


  webSocket.begin("10.107.233.122", 8000, "/ws/device");
  

  webSocket.setReconnectInterval(5000);


  Serial.println("WebSocket Started");

}



void loop() {


  webSocket.loop();


  unsigned long currentTime = micros();


  if(currentTime - lastSampleTime >= SAMPLE_INTERVAL){

    lastSampleTime = currentTime;


    int ecgValue = analogRead(ECG_PIN);


    String data = String(ecgValue);


    webSocket.sendTXT(data);


    Serial.println(ecgValue);

  }

}
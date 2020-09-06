import asyncio
import argparse
import aiohttp
import sys
import json
import time
import re
import logging

#11800 11801 11802 11803 11804

API_KEY = ''

link = 'https://maps.googleapis.com/maps/api/place/nearbysearch/json?'
log_file = ''

ports = {
	'Hill': 11800,
	'Jaquez': 11801,
	'Smith': 11802,
	'Campbell': 11803,
	'Singleton': 11804    
}

port_routes = { #web of interdependencies
	'Hill': ['Jaquez', 'Smith'],
	'Jaquez': ['Hill', 'Singleton'],
	'Smith': ['Hill', 'Campbell', 'Singleton'],
	'Campbell': ['Smith', 'Singleton'],
	'Singleton': ['Jaquez', 'Smith', 'Campbell']
}

clients = {} #keeps track of visited clients

class Server: #server class
    def __init__(self, name, ip='127.0.0.1', message_max_length=1e6):
        self.name = name
        self.ip = ip
        self.port = ports[name]
        self.message_max_length = int(message_max_length)   

    async def server_write(self, writer, message): #writes TCP messages to server
        try:
            writer.write(message.encode())
            await writer.drain()
            writer.close()
        except:
            print('Invalid write to server. \n')

    async def log_write(self, message): #writes to the log file
        logging.info(message)

    async def flood(self, message): #propagates message to all other servers in the web

        #print(sys.argv[1])
        for server in port_routes[self.name]: #check all server names in the port_routes
            await self.log_write('Attempting to flood from ' + self.name + ' to ' + server + '\n')
            try:
                #print('before')
                #print(ports[server])
                (reader, writer) = await asyncio.open_connection(self.ip, ports[server]) #check if connection can be made in try/except
                #print('after')
                await self.log_write('Successful flood' + '\n')
                await self.server_write(writer, message)
            except:
                await self.log_write('Failed to flood' + '\n')
                

    async def handle_input(self, reader, writer):
        data = await reader.read(self.message_max_length)
        message = data.decode()
        await self.log_write("RECEIVED " + message + '\n')
        arr = message.strip().split()
        error_message = '? ' + message
        time_received = time.time()
        #print(arr[0])   
        if self.valid_message(arr):
            if arr[0] == 'IAMAT':
                host = arr[1]
                latlong = arr[2]
                time_sent = arr[3]
                time_difference = time_received - float(time_sent)
                if time_difference >= 0:
                    time_difference = '+' + str(time_difference)
                else:
                    time_difference = str(time_difference)
                out_message = 'AT ' + self.name + ' ' + time_difference + ' ' + host + ' ' + latlong + ' ' + time_sent #message to write to server
                flood_message = 'PROPAGATE ' + host + ' ' + latlong + ' ' + time_sent + ' ' + self.name + ' ' + str(time_received) #message to propagate
                clients[host] = [latlong, time_sent, self.name, str(time_received)] #appropriately update clients
                asyncio.ensure_future(self.flood(flood_message)) #propagate message
                await self.log_write("SENDING " + out_message + '\n') #write to log
                await self.server_write(writer, out_message)
                

            elif arr[0] == 'PROPAGATE':    #we need to propagate a propagate message
                host = arr[1]
                latlong = arr[2]
                time_sent = arr[3]
                if host in clients: #check if its host is in our web of clients
                    if float(time_sent) > float(clients[host][1]):
                        clients[host] = [arr[2],arr[3],arr[4],arr[5]]
                        await self.flood(message) #flood
                else:
                    clients[host] = [arr[2],arr[3],arr[4],arr[5]]
                    await self.flood(message) #flood
                    
            elif arr[0] == 'WHATSAT': #handle a whatsat message
                host = arr[1]
                rad = 1000*int(arr[2])
                if host not in clients:
                    await self.log_write("SENDING " + error_message + '\n')  #log that we are sending an error message
                    await self.server_write(writer, error_message) 
                else:
                    client_latlong = clients[host][0]
                    client_time_sent = clients[host][1]
                    client_server_name = clients[host][2]
                    server_time_received = clients[host][3] 

                    latitude = self.get_lat_long(client_latlong)[0]
                    longitude = self.get_lat_long(client_latlong)[1]    
                    loc = "{0},{1}".format(latitude, longitude)
                    url = 'https://maps.googleapis.com/maps/api/place/nearbysearch/json?key={0}&location={1}&radius={2}'.format(API_KEY, loc, rad)

                    time_difference = float(server_time_received) - float(client_time_sent)
                    if time_difference >= 0:
                        time_difference = '+' + str(time_difference)
                    else:
                        time_difference = str(time_difference)
                    out_message = 'AT ' + client_server_name + ' ' + time_difference + ' ' + host + ' ' + client_latlong + ' ' + client_time_sent + '\n'
                    out_message += await self.simple_case(url) #get request

                    await self.log_write("SENDING " + out_message)
                    await self.server_write(writer, out_message)
                #print('whatsat')
                
        else:
            await self.server_write(writer, error_message)
            await self.log_write('Invalid message: ' + error_message + '\n')

    async def simple_case(self, url): #making the request
        async with aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(
                ssl=False,
            ),
        ) as session:
            async with session.get(url) as resp:
                response = await resp.json()
                response['results'] = response['results'][:3]
                return json.dumps(response, indent = 3) + '\n\n'

    def get_lat_long(self, lat_long): #extract the latitude and longitude from the appended string
        i = 0
        signs = []
        while i < len(lat_long):
            if lat_long[i] == '+' or lat_long[i] == '-':
                signs.append(i)
            i += 1
        lat = lat_long[:signs[1]]
        longi = lat_long[signs[1]:]
        if lat[0] == '+':
            lat = lat[1:]
        if longi[0] == '+':
            longi = longi[1:]
        return [lat, longi]

    def valid_message(self, arr): #check if a command is valid
        if arr[0] == 'IAMAT':
            if len(arr) == 4 and self.isFloat(arr[3]):
                return self.validlatlong(arr[2])
            else:
                return False
        elif arr[0] == 'PROPAGATE':
            return True
        elif arr[0] == 'WHATSAT':
            return len(arr) == 4 and self.isInt(arr[2]) and self.isInt(arr[3]) and int(arr[2]) <= 50 and int(arr[3]) <= 20
        else:
            return False

    def isFloat(self, s):
        verdict = True
        try:
            time = float(s)
        except:
            verdict = False
        return verdict

    def isInt(self, s):
        verdict = True
        try:
            time = int(s)
        except:
            verdict = False
        return verdict

    def validlatlong(self, latlong):        #check if a latitude longitude string is valid
        if latlong[0] != '+' and latlong[0] != '-':
            return False
        if latlong[-1] == '+' or latlong[-1] == '-':
            return False
        i = 0
        signs = []
        while i < len(latlong):
            if latlong[i] == '+' or latlong[i] == '-':
                signs.append(i)
            i += 1
        if len(signs) != 2:
            return False
        verdict = True
        try:
            lat = float(latlong[:signs[1]])
            longi = float(latlong[signs[1]:])
        except:
            verdict = False
        return verdict

    def run_forever(self): #responsible for starting server until we exit
        self.loop = asyncio.get_event_loop()
        coro = asyncio.start_server(self.handle_input, self.ip, self.port, loop=self.loop)
        server = self.loop.run_until_complete(coro)

        try:
            self.loop.run_forever()
        except KeyboardInterrupt:
            pass
        
        server.close()
        self.loop.run_until_complete(server.wait_closed())
        self.loop.close()

def main():

    if len(sys.argv) != 2:
        print("Invalid argument length")
        exit()
    if sys.argv[1] not in ports:
        print("Invalid server name")
        exit()

    #print(sys.argv[1])
    global log_file
    logging.basicConfig(filename=sys.argv[1]+'.txt', filemode='w', level=logging.INFO)

    server = Server(sys.argv[1])
    server.run_forever()


if __name__ == '__main__':
    main()
